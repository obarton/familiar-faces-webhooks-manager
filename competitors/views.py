import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from . import ai_client, firecrawl_client, social_client, youtube_client
from .forms import CompetitorSourceForm
from .models import CompetitorContentItem, CompetitorSource, LandscapeReport

logger = logging.getLogger(__name__)

FEED_LIMIT = 100

# Format badges -> (display label, DB filter). Mirrors CompetitorContentItem.format_label.
FORMAT_FILTERS = {
    'instagram_reel': ('Instagram Reel', Q(platform='instagram', content_type='reel')),
    'instagram_post': ('Instagram Post', Q(platform='instagram') & ~Q(content_type='reel')),
    'tiktok_video':   ('TikTok Video',   Q(platform='tiktok')),
    'youtube_video':  ('YouTube Video',  Q(platform='youtube')),
    'article':        ('Article',        Q(platform='website')),
}


@login_required
def dashboard(request):
    # Own-brand accounts first, then competitors, each alphabetical.
    sources = list(CompetitorSource.objects.order_by('-is_own_brand', 'name'))

    all_items = CompetitorContentItem.objects.select_related('source')

    # Feed ordered by when the content was published (newest first). Items with
    # no published date fall to the bottom, then by when we first saw them.
    items = all_items.order_by(F('published_date').desc(nulls_last=True), '-created_at')

    active_source_id = request.GET.get('source') or ''
    selected_source = None
    if active_source_id:
        selected_source = next(
            (s for s in sources if str(s.id) == active_source_id), None
        )
        if selected_source:
            items = items.filter(source=selected_source)

    active_format = request.GET.get('format') or ''
    if active_format in FORMAT_FILTERS:
        items = items.filter(FORMAT_FILTERS[active_format][1])
    else:
        active_format = ''  # ignore unknown values

    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    parsed_from = parse_date(date_from) if date_from else None
    parsed_to = parse_date(date_to) if date_to else None
    if parsed_from:
        items = items.filter(published_date__gte=parsed_from)
    if parsed_to:
        items = items.filter(published_date__lte=parsed_to)

    query = request.GET.get('q', '').strip()
    if query:
        items = items.filter(
            Q(title__icontains=query)
            | Q(summary__icontains=query)
            | Q(description__icontains=query)
            | Q(source__name__icontains=query)
        )

    items = list(items[:FEED_LIMIT])

    last_refreshed = max(
        (s.last_crawled_at for s in sources if s.last_crawled_at), default=None
    )

    return render(request, 'competitors/dashboard.html', {
        'sources': sources,
        'items': items,
        'selected_source': selected_source,
        'query': query,
        'active_format': active_format,
        'format_options': [(key, label) for key, (label, _) in FORMAT_FILTERS.items()],
        'date_from': date_from,
        'date_to': date_to,
        'has_filters': bool(query or selected_source or active_format or parsed_from or parsed_to),
        'total_items': all_items.count(),
        'competitor_count': len(sources),
        'last_refreshed': last_refreshed,
        # YouTube works with either the Data API (preferred) or Firecrawl scraping.
        'youtube_configured': youtube_client.is_configured() or firecrawl_client.is_configured(),
        'apify_configured': social_client.is_configured(),
    })


def _render_report_html(markdown_text):
    """Render a landscape report's markdown to safe HTML for display."""
    if not markdown_text:
        return None
    import markdown as md
    return mark_safe(md.markdown(
        markdown_text, extensions=['tables', 'fenced_code', 'sane_lists']
    ))


@login_required
def landscape(request):
    report = LandscapeReport.latest_ready()
    run = LandscapeReport.active_run()
    history = LandscapeReport.history()
    if report:
        history = history.exclude(pk=report.pk)
    return render(request, 'competitors/landscape.html', {
        'report': report,
        'run': run,
        'report_html': _render_report_html(report.markdown if report else None),
        'history': list(history),
        'ai_configured': ai_client.is_configured(),
        'has_sources': CompetitorSource.objects.exists(),
    })


@login_required
def landscape_detail(request, id):
    report = get_object_or_404(LandscapeReport.history(), id=id)
    return render(request, 'competitors/landscape_detail.html', {
        'report': report,
        'report_html': _render_report_html(report.markdown),
    })


@login_required
@require_POST
def landscape_generate(request):
    # Generation is slow (web search) and must not run inline — it would trip the
    # gunicorn worker timeout. Queue it; the refresh_competitors worker generates it.
    if not ai_client.is_configured():
        messages.warning(request, 'Set ANTHROPIC_API_KEY to generate the landscape report.')
    elif not CompetitorSource.objects.exists():
        messages.info(request, 'Add some accounts first, then generate the landscape.')
    else:
        LandscapeReport.queue(trigger=LandscapeReport.TRIGGER_MANUAL)
        messages.success(
            request,
            'Landscape report queued — the background worker will generate it shortly '
            '(web search takes a few minutes). This page refreshes itself while it runs.',
        )
    return redirect('competitors:landscape')


@login_required
def source_create(request):
    form = CompetitorSourceForm(request.POST or None)
    if form.is_valid():
        # New sources default to refresh_requested=True, so the worker picks them
        # up on its next pass.
        source = form.save()
        kind = 'Brand account' if source.is_own_brand else 'Competitor'
        messages.success(
            request,
            f'{kind} "{source.name}" added and queued — content will appear after the next refresh.',
        )
        return redirect('competitors:dashboard')
    return render(request, 'competitors/source_form.html', {'form': form})


def _recent_items(source, limit=FEED_LIMIT):
    return list(
        CompetitorContentItem.objects
        .filter(source=source)
        .order_by(F('published_date').desc(nulls_last=True), '-created_at')[:limit]
    )


@login_required
def competitor_detail(request, id):
    source = get_object_or_404(CompetitorSource, id=id)
    items = _recent_items(source)

    # Generate the AI summary on first view (cached thereafter), so the page
    # "just has" a summary without a separate click.
    if not source.ai_summary and ai_client.is_configured() and items:
        ai_client.generate_and_store(source, items)

    return render(request, 'competitors/competitor_detail.html', {
        'source': source,
        'items': items,
        'ai_configured': ai_client.is_configured(),
        'brand_name': settings.BRAND_NAME,
    })


@login_required
@require_POST
def competitor_summary(request, id):
    source = get_object_or_404(CompetitorSource, id=id)
    if not ai_client.is_configured():
        messages.warning(request, 'Set ANTHROPIC_API_KEY to generate AI summaries.')
    elif ai_client.generate_and_store(source, _recent_items(source)):
        messages.success(request, 'Summary regenerated.')
    else:
        messages.warning(request, 'Could not generate a summary — check the logs.')
    return redirect('competitors:competitor_detail', id=source.id)


@login_required
def source_delete(request, id):
    source = get_object_or_404(CompetitorSource, id=id)
    if request.method == 'POST':
        name = source.name
        source.delete()
        messages.success(request, f'Competitor "{name}" removed.')
        return redirect('competitors:dashboard')
    item_count = source.items.count()
    return render(request, 'competitors/source_confirm_delete.html', {
        'source': source,
        'item_count': item_count,
    })


@login_required
@require_POST
def source_refresh(request, id):
    # Queue only — the refresh_competitors worker does the crawl in the background
    # so the request never blocks on slow (and paid) scrapes.
    source = get_object_or_404(CompetitorSource, id=id)
    if not source.refresh_requested:
        source.refresh_requested = True
        source.save(update_fields=['refresh_requested', 'updated_at'])
    messages.success(
        request,
        f'Refresh queued for "{source.name}" — content updates shortly.',
    )
    return redirect('competitors:dashboard')


@login_required
@require_POST
def refresh_all(request):
    updated = CompetitorSource.objects.filter(
        is_active=True, refresh_requested=False
    ).update(refresh_requested=True)
    active = CompetitorSource.objects.filter(is_active=True).count()
    if active == 0:
        messages.info(request, 'No active competitors to refresh.')
    else:
        messages.success(
            request,
            f'Queued {active} competitor(s) for refresh — content updates shortly.',
        )
    return redirect('competitors:dashboard')
