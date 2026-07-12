"""Firecrawl integration for the competitor content tracker.

Mirrors the fault-tolerance contract of webhooks/sheets.py and
webhooks/mailchimp_client.py: a lazily-initialised singleton client built from an
env-var API key, every network call wrapped so failures are logged and the caller
gets an empty/neutral result instead of an exception. A missing FIRECRAWL_API_KEY
degrades the feature gracefully rather than breaking the page.

Used only for YouTube here: scrape() the channel page plus an LLM JSON-extract that
returns a list of recent videos. Instagram/TikTok go through social_client (Apify).
Failures never raise — they log and yield no items for that channel.
"""
import logging
import re
from datetime import date, datetime, timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_client = None

# JSON-extract schema for a social profile: a LIST of the recent posts/videos.
_SOCIAL_SCHEMA = {
    'type': 'object',
    'properties': {
        'items': {
            'type': 'array',
            'description': 'The most recent posts or videos visible on this profile/channel.',
            'items': {
                'type': 'object',
                'properties': {
                    'url': {'type': 'string', 'description': 'Direct link to the post/video.'},
                    'title': {'type': 'string', 'description': 'Caption, title, or short description.'},
                    'summary': {'type': 'string', 'description': 'One-sentence summary of the content.'},
                    'published_date': {
                        'type': 'string',
                        'description': (
                            'The publish time exactly as shown — an absolute date if '
                            "present, otherwise the relative text such as '2 days ago' "
                            "or '3 weeks ago'. Empty if none is shown."
                        ),
                    },
                    'keywords': {'type': 'array', 'items': {'type': 'string'}},
                },
            },
        },
    },
}


def is_configured():
    return bool(getattr(settings, 'FIRECRAWL_API_KEY', ''))


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = getattr(settings, 'FIRECRAWL_API_KEY', '')
    if not api_key:
        return None
    # Imported lazily so the app boots (and unrelated pages work) even if the
    # firecrawl-py package is not installed in some environment.
    from firecrawl import Firecrawl
    _client = Firecrawl(api_key=api_key)
    return _client


# Approximate days-per-unit for relative "N <unit> ago" strings. Weeks/months/
# years are deliberately approximate (30/365) — good enough for a competitor
# tracker where the exact day of an older upload doesn't matter.
_RELATIVE_UNIT_DAYS = {
    'second': 0, 'minute': 0, 'hour': 0,
    'day': 1, 'week': 7, 'month': 30, 'year': 365,
}
# e.g. "2 days ago", "a week ago", "streamed 3 weeks ago", "Premiered 1 month ago".
_RELATIVE_RE = re.compile(
    r'(?:streamed|premiered)?\s*'
    r'(?P<qty>\d+|a|an)\s+'
    r'(?P<unit>second|minute|hour|day|week|month|year)s?\s+ago',
    re.IGNORECASE,
)


def _parse_relative_date(text, now):
    """Parse YouTube-style relative time ('2 days ago', 'yesterday') into a date
    anchored at `now` (the scrape time). Returns None if not recognised."""
    lowered = text.lower()
    if lowered in ('today', 'just now'):
        return now.date()
    if lowered == 'yesterday':
        return (now - timedelta(days=1)).date()
    match = _RELATIVE_RE.search(lowered)
    if not match:
        return None
    qty_raw = match.group('qty')
    qty = 1 if qty_raw in ('a', 'an') else int(qty_raw)
    days = _RELATIVE_UNIT_DAYS[match.group('unit')] * qty
    return (now - timedelta(days=days)).date()


def _parse_date(value, now=None):
    """Best-effort parse of a metadata/extracted date into a date, else None.

    Handles ISO 8601 and common absolute formats, then falls back to relative
    text like '2 days ago' (what YouTube channel grids actually show), anchored
    at `now` (defaults to the current time)."""
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    # ISO 8601 (with or without time / trailing Z) covers metadata.published_time.
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).date()
    except ValueError:
        pass
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%B %d, %Y', '%b %d, %Y', '%d %B %Y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return _parse_relative_date(text, now or timezone.now())


def _clean_keywords(raw):
    if isinstance(raw, str):
        raw = [k.strip() for k in raw.split(',')]
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(k).strip() for k in raw if str(k).strip()][:8]


def _is_unsupported_site_error(exc):
    """Firecrawl raises WebsiteNotSupportedError for sites it can't scrape
    (Instagram, TikTok, etc.). Match by class name so we don't depend on the
    SDK's internal import path, with a message fallback."""
    return (
        type(exc).__name__ == 'WebsiteNotSupportedError'
        or 'do not support this site' in str(exc).lower()
    )


def _scrape_social(url, platform, label):
    """Scrape a social profile page and extract recent posts/videos.

    Returns (items, supported). supported is False only when Firecrawl reports the
    site as unsupported (Instagram/TikTok), so the caller can tell the user why the
    channel is empty rather than treating it as a transient failure.
    """
    client = _get_client()
    prompt = (
        f'This is a competitor\'s {label} profile or channel page. Extract the most '
        f'recent posts or videos shown, each with a direct URL, its caption/title, a '
        f'one-sentence summary, the publish time exactly as shown (an absolute date if '
        f"present, otherwise relative text like '2 days ago' or '3 weeks ago'), and 3-6 "
        f'topic keywords. Return an empty list if none are visible.'
    )
    try:
        from firecrawl.v2.types import JsonFormat

        doc = client.scrape(
            url,
            formats=['markdown', JsonFormat(type='json', prompt=prompt, schema=_SOCIAL_SCHEMA)],
            only_main_content=False,
        )
        extracted = getattr(doc, 'json', None) or {}
        raw_items = extracted.get('items') or []
        # Anchor every relative date ("2 days ago") in this batch to one scrape time.
        now = timezone.now()
        items, seen = [], set()
        skipped_no_url = 0
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item_url = str(raw.get('url', '') or '').strip()
            if not item_url:
                skipped_no_url += 1
                continue
            if item_url in seen:
                continue
            seen.add(item_url)
            items.append({
                'platform': platform,
                'content_type': 'video' if platform == 'youtube' else '',
                'url': item_url,
                'title': str(raw.get('title', '') or '').strip()[:500],
                'description': '',
                'summary': str(raw.get('summary', '') or '').strip(),
                'keywords': _clean_keywords(raw.get('keywords')),
                'published_date': _parse_date(raw.get('published_date'), now),
            })
        if skipped_no_url:
            logger.info(
                '%s scrape for %s: skipped %d item(s) with no URL', label, url, skipped_no_url,
            )
        return items, True
    except Exception as exc:
        if _is_unsupported_site_error(exc):
            # Expected for Instagram/TikTok — log a clean line, no traceback.
            logger.warning('Firecrawl does not support %s (%s); skipping this channel.', label, url)
            return [], False
        logger.warning('Firecrawl %s scrape failed for %s', label, url, exc_info=True)
        return [], True


def crawl_source(source, limit=None):
    """Collect content across all of a source's configured channels.

    `limit` caps items fetched per channel; defaults to the source's crawl_limit.
    YouTube uses the Data API when YOUTUBE_API_KEY is set, else Firecrawl scraping;
    Instagram + TikTok use the Apify provider (Firecrawl can't read them).
    Returns (items, unsupported, needs_provider):
      unsupported    - channels the provider reports it can't scrape
      needs_provider - Instagram/TikTok channels present but Apify not configured
    Never raises.
    """
    from . import social_client, youtube_client

    if limit is None:
        limit = source.crawl_limit

    firecrawl_ok = bool(_get_client())
    items = []
    unsupported = []
    needs_provider = []

    for channel in source.channels:
        platform = channel['platform']
        label = channel['label']

        if platform in ('instagram', 'tiktok'):
            if social_client.is_configured():
                ch_items, status = social_client.fetch(
                    channel['url'], platform, label, limit
                )
                items.extend(ch_items)
                if status != 'ok':
                    unsupported.append(label)
            else:
                needs_provider.append(label)
            continue

        # youtube: prefer the official Data API (exact dates + view/like counts);
        # fall back to Firecrawl channel-page scraping when no YOUTUBE_API_KEY.
        if youtube_client.is_configured():
            ch_items, status = youtube_client.fetch(source, channel['url'], label, limit)
            items.extend(ch_items)
            if status != 'ok':
                unsupported.append(label)
            continue
        if not firecrawl_ok:
            logger.warning(
                'YouTube channel skipped: neither YOUTUBE_API_KEY nor FIRECRAWL_API_KEY '
                'is set. source=%r channel=%s', source.name, label,
            )
            continue
        ch_items, supported = _scrape_social(channel['url'], platform, label)
        items.extend(ch_items)
        if not supported:
            unsupported.append(label)

    return items, unsupported, needs_provider


def refresh_source(source, limit=None):
    """Crawl/scrape every channel of `source` and upsert its content items.

    Run by the refresh_competitors worker. Crawls every channel, upserts items,
    and records status on the source (last_crawled_at, last_refresh_status,
    last_refresh_note) while clearing the refresh_requested queue flag. Returns a
    summary dict.

    Limit precedence: an explicit `limit` (e.g. the command's --limit) wins;
    otherwise the first refresh of a new competitor pulls COMPETITOR_BACKFILL_LIMIT
    and recurring refreshes use the source's crawl_limit.
    """
    if limit is None:
        if source.backfill_requested:
            limit = getattr(settings, 'COMPETITOR_BACKFILL_LIMIT', 200)
        else:
            limit = source.crawl_limit

    items, unsupported, needs_provider = crawl_source(source, limit)
    created = 0
    from .models import CompetitorContentItem  # local import avoids app-loading order issues

    for data in items:
        _, was_created = CompetitorContentItem.objects.update_or_create(
            source=source,
            url=data['url'],
            defaults={
                'platform': data['platform'],
                'content_type': data.get('content_type', ''),
                'title': data['title'],
                'description': data['description'],
                'summary': data['summary'],
                'keywords': data['keywords'],
                'published_date': data['published_date'],
            },
        )
        if was_created:
            created += 1

    # Build a short human note about skipped channels for the dashboard.
    notes = []
    if needs_provider:
        notes.append(f'{", ".join(needs_provider)} need APIFY_API_TOKEN')
    if unsupported:
        notes.append(f'{", ".join(unsupported)} could not be read')

    source.last_crawled_at = timezone.now()
    source.last_refresh_status = f'{created} new / {len(items)} scanned'
    source.last_refresh_note = '; '.join(notes)
    source.refresh_requested = False
    source.backfill_requested = False  # deep first pull done; recurring uses crawl_limit
    source.save(update_fields=[
        'last_crawled_at', 'last_refresh_status', 'last_refresh_note',
        'refresh_requested', 'backfill_requested', 'updated_at',
    ])

    return {
        'created': created,
        'seen': len(items),
        'unsupported': unsupported,
        'needs_provider': needs_provider,
    }
