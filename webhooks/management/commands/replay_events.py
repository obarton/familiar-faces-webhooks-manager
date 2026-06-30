from django.core.management.base import BaseCommand

from webhooks.models import WebhookEndpoint, WebhookEvent
from webhooks.sheets import cached_sheet_rows
from webhooks.views import _process_event


class Command(BaseCommand):
    help = (
        "Re-process stored webhook events in place: re-run event/market tag "
        "resolution and Mailchimp sync for each event, updating its sheet_tag / "
        "mailchimp_tag. Useful for backfilling events that were received before a "
        "tag-matching fix. Does NOT create new event rows. The Google Sheet is "
        "fetched once per run (not once per event). Note: events with an "
        "account_email are re-synced to Mailchimp (idempotent, but real API "
        "calls) -- use --dry-run / --limit / --only-untagged to scope a run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--endpoint',
            help='Endpoint slug to limit replay to (default: all endpoints).',
        )
        parser.add_argument(
            '--only-untagged',
            action='store_true',
            help='Only re-process events that currently have no sheet_tag and no '
                 'mailchimp_tag.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Maximum number of events to process.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be processed without calling integrations or '
                 'writing to the database.',
        )

    def handle(self, *args, **options):
        qs = WebhookEvent.objects.all().order_by('created_at')

        slug = options.get('endpoint')
        if slug:
            endpoint = WebhookEndpoint.objects.filter(slug=slug).first()
            if not endpoint:
                self.stderr.write(
                    self.style.ERROR(f"replay_events: no endpoint with slug {slug!r}.")
                )
                return
            qs = qs.filter(endpoint=endpoint)

        if options.get('only_untagged'):
            qs = qs.filter(sheet_tag__isnull=True, mailchimp_tag__isnull=True)

        total = qs.count()
        limit = options.get('limit')
        if limit is not None:
            qs = qs[:limit]

        planned = min(total, limit) if limit is not None else total
        scope = f"endpoint {slug!r}" if slug else "all endpoints"
        self.stdout.write(
            f"replay_events: {planned} event(s) to process for {scope}"
            f"{' (only untagged)' if options.get('only_untagged') else ''}"
            f"{' [dry run]' if options.get('dry_run') else ''}."
        )

        if options.get('dry_run'):
            self.stdout.write(
                self.style.SUCCESS(f"replay_events: dry run -- would process {planned} event(s).")
            )
            return

        processed = 0
        tagged = 0
        with cached_sheet_rows():
            for event in qs.iterator():
                _process_event(event)
                processed += 1
                if event.sheet_tag or event.mailchimp_tag:
                    tagged += 1
                if processed % 25 == 0:
                    self.stdout.write(f"replay_events: processed {processed}/{planned}...")

        self.stdout.write(
            self.style.SUCCESS(
                f"replay_events: processed {processed} event(s); "
                f"{tagged} now carry a tag."
            )
        )
