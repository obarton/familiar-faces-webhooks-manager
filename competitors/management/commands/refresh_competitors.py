import time
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from competitors import ai_client, firecrawl_client, social_client
from competitors.models import CompetitorSource, LandscapeReport


class Command(BaseCommand):
    help = (
        "Background worker that crawls competitor sources and stores their content. "
        "Processes sources that were queued from the UI (refresh_requested) or have "
        "gone stale. Run once from cron, or continuously with --loop."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--loop',
            type=int,
            metavar='SECONDS',
            help='Run continuously, sleeping SECONDS between passes (e.g. --loop 900).',
        )
        parser.add_argument(
            '--max-age',
            type=int,
            default=360,
            help='Auto-refresh active sources whose last crawl is older than this '
                 'many minutes (default 360). Queued sources always refresh.',
        )
        parser.add_argument(
            '--queued-only',
            action='store_true',
            help='Only refresh sources queued from the UI; skip the staleness sweep.',
        )
        parser.add_argument(
            '--source',
            help='Refresh sources matching this name or id now, regardless of queue/staleness.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Items per channel for this run (overrides recurring/backfill limits). '
                 'Use for a one-off deep pull, e.g. --limit 200.',
        )
        parser.add_argument(
            '--include-inactive',
            action='store_true',
            help='Also consider sources marked inactive.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List which sources would be crawled without crawling.',
        )
        parser.add_argument(
            '--no-auto-landscape',
            action='store_true',
            help='Skip the monthly landscape auto-regeneration sweep. UI-queued '
                 'landscape reports are still generated.',
        )

    def handle(self, *args, **options):
        loop_secs = options.get('loop')
        if loop_secs:
            self.stdout.write(self.style.SUCCESS(
                f'refresh_competitors worker started (every {loop_secs}s). Ctrl-C to stop.'
            ))
            try:
                while True:
                    self._run_pass(options)
                    time.sleep(loop_secs)
            except KeyboardInterrupt:
                self.stdout.write('\nWorker stopped.')
        else:
            self._run_pass(options)

    def _select_sources(self, options):
        qs = CompetitorSource.objects.all()
        if not options['include_inactive']:
            qs = qs.filter(is_active=True)

        source_filter = options.get('source')
        if source_filter:
            # Explicit target: refresh matches now, ignoring queue/staleness.
            q = Q(name__icontains=source_filter)
            try:
                q |= Q(id=uuid.UUID(source_filter))
            except (ValueError, TypeError, AttributeError):
                pass
            return list(qs.filter(q))

        # Due = queued from the UI, plus (unless --queued-only) anything stale.
        due = Q(refresh_requested=True)
        if not options['queued_only']:
            cutoff = timezone.now() - timedelta(minutes=options['max_age'])
            due |= Q(last_crawled_at__isnull=True) | Q(last_crawled_at__lt=cutoff)
        return list(qs.filter(due))

    # Keep this many finished landscape reports; older ones are pruned.
    _LANDSCAPE_HISTORY_LIMIT = 12

    def _landscape_regeneration_due(self):
        """True if the monthly landscape sweep should auto-queue a report now: AI
        configured, some accounts tracked, nothing already pending, and no report
        row created yet this calendar month (so exactly one auto-attempt per month,
        even if it fails)."""
        if not ai_client.is_configured() or not CompetitorSource.objects.exists():
            return False
        if LandscapeReport.objects.filter(generation_requested=True).exists():
            return False
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return not LandscapeReport.objects.filter(created_at__gte=month_start).exists()

    def _prune_landscape_history(self):
        """Keep only the newest _LANDSCAPE_HISTORY_LIMIT finished reports."""
        stale = list(
            LandscapeReport.history()
            .values_list('id', flat=True)[self._LANDSCAPE_HISTORY_LIMIT:]
        )
        if stale:
            LandscapeReport.objects.filter(id__in=stale).delete()

    def _process_landscape(self, options):
        """Generate the landscape report if one is queued (from the UI or the monthly
        sweep). Runs off the request path here because web search is too slow for a
        web request."""
        # Monthly auto-regeneration: queue a report the first pass of each new month.
        if not options.get('no_auto_landscape') and self._landscape_regeneration_due():
            if options['dry_run']:
                self.stdout.write('[dry-run] would auto-queue the monthly landscape report')
            else:
                LandscapeReport.queue(trigger=LandscapeReport.TRIGGER_SCHEDULED)
                self.stdout.write('Auto-queued the monthly landscape report.')

        report = LandscapeReport.objects.filter(generation_requested=True).first()
        if not report:
            return

        if options['dry_run']:
            self.stdout.write('[dry-run] would generate the queued landscape report')
            return

        if not ai_client.is_configured():
            report.status = LandscapeReport.STATUS_FAILED
            report.last_error = 'ANTHROPIC_API_KEY is not set on the worker.'
            report.generation_requested = False
            report.save(update_fields=['status', 'last_error', 'generation_requested', 'updated_at'])
            self.stderr.write(self.style.ERROR(
                'Landscape report queued but ANTHROPIC_API_KEY is not set on the worker.'
            ))
            return

        self.stdout.write('Generating landscape report (web search)…')
        try:
            ok = ai_client.generate_and_store_landscape(report)
        except Exception as exc:  # guarded internally, but never kill the pass
            self.stderr.write(self.style.ERROR(f'Landscape generation errored: {exc}'))
            return
        if ok:
            self._prune_landscape_history()
            self.stdout.write(self.style.SUCCESS('Landscape report generated.'))
        else:
            self.stderr.write(self.style.ERROR('Landscape report generation failed — see logs.'))

    def _run_pass(self, options):
        # Landscape generation is independent of the crawl providers, so process it
        # before the crawl (and its provider guard below).
        self._process_landscape(options)

        if not firecrawl_client.is_configured() and not social_client.is_configured():
            if not options.get('loop'):
                self.stdout.write(
                    'No crawl provider configured (FIRECRAWL_API_KEY / APIFY_API_TOKEN); skipping crawl.'
                )
            return

        sources = self._select_sources(options)
        if not sources:
            if not options.get('loop'):
                self.stdout.write('No competitors are due for refresh.')
            return

        limit_override = options.get('limit')
        total_created = 0
        total_seen = 0

        for source in sources:
            if options['dry_run']:
                self.stdout.write(f'[dry-run] would crawl {source.name}')
                continue

            try:
                # limit_override (--limit) wins; else refresh_source auto-picks
                # backfill vs recurring limit.
                result = firecrawl_client.refresh_source(source, limit=limit_override)
            except Exception as exc:  # refresh_source shouldn't raise, but never kill the loop
                self.stderr.write(self.style.ERROR(f'{source.name}: refresh failed: {exc}'))
                continue

            total_created += result['created']
            total_seen += result['seen']
            line = f'{source.name}: {result["created"]} new / {result["seen"]} scanned'
            notes = []
            if result.get('needs_provider'):
                notes.append(f'needs APIFY_API_TOKEN: {", ".join(result["needs_provider"])}')
            if result.get('unsupported'):
                notes.append(f'unsupported: {", ".join(result["unsupported"])}')
            if notes:
                line += f' ({"; ".join(notes)})'
            self.stdout.write(line)

        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS(f'[dry-run] {len(sources)} source(s) due.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Done. {total_created} new across {len(sources)} source(s); {total_seen} scanned.'
            ))
