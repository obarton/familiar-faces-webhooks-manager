"""Apify integration for Instagram and TikTok content.

Firecrawl can't read Instagram/TikTok (they block generic scraping), so those two
channels route here instead. Same fault-tolerance contract as firecrawl_client.py:
a lazily-built singleton client from an env-var token, every network call wrapped
so failures log and return neutral results. No token = feature degrades gracefully
(the caller reports the channel as needing configuration).

Actor output shapes (per Apify docs):
  apify/instagram-scraper posts:  url, caption, timestamp, likesCount, commentsCount, hashtags
  clockworks/tiktok-scraper videos: webVideoUrl, text, createTimeISO, diggCount, playCount, commentCount, hashtags
"""
import logging
import re
from datetime import timedelta

from django.conf import settings

# Reuse the tolerant date parser already written for Firecrawl content.
from .firecrawl_client import _parse_date

logger = logging.getLogger(__name__)

_client = None

# Bound each actor run so a hung scrape can't wedge the worker pass.
_ACTOR_TIMEOUT_SECS = 180


def is_configured():
    return bool(getattr(settings, 'APIFY_API_TOKEN', ''))


def _get_client():
    global _client
    if _client is not None:
        return _client
    token = getattr(settings, 'APIFY_API_TOKEN', '')
    if not token:
        return None
    # Imported lazily so the app boots even if apify-client isn't installed.
    from apify_client import ApifyClient
    _client = ApifyClient(token)
    return _client


def _fmt(n):
    """Compact engagement count: 1234 -> '1,234', 12000 -> '12,000'."""
    try:
        return f'{int(n):,}'
    except (TypeError, ValueError):
        return None


def _hashtag_names(raw):
    """Normalize a hashtags field that may be list[str] or list[{'name': ...}]."""
    out = []
    for h in raw or []:
        if isinstance(h, dict):
            h = h.get('name') or h.get('hashtag') or ''
        h = str(h).strip().lstrip('#')
        if h:
            out.append(h)
    return out[:8]


def _tiktok_handle(url):
    """Extract the @handle from a TikTok profile URL; fall back to the URL."""
    match = re.search(r'@([\w.]+)', url or '')
    return match.group(1) if match else url


def _engagement(parts):
    """Join present 'N label' fragments into a summary string."""
    return ' · '.join(p for p in parts if p)


def _iterate_dataset(client, run):
    if not run:
        return []
    dataset_id = run.get('defaultDatasetId') if isinstance(run, dict) else getattr(run, 'default_dataset_id', None)
    if not dataset_id:
        return []
    return list(client.dataset(dataset_id).iterate_items())


def _fetch_instagram(client, url, limit):
    run = client.actor(settings.APIFY_INSTAGRAM_ACTOR).call(
        run_input={
            'directUrls': [url],
            'resultsType': 'posts',
            'resultsLimit': limit,
        },
        max_items=limit,
        run_timeout=timedelta(seconds=_ACTOR_TIMEOUT_SECS),
    )
    items = []
    for post in _iterate_dataset(client, run):
        post_url = str(post.get('url', '') or '').strip()
        if not post_url:
            continue
        summary = _engagement([
            _like_str(post.get('likesCount'), 'likes'),
            _like_str(post.get('commentsCount'), 'comments'),
        ])
        product = str(post.get('productType', '') or '').lower()
        media = str(post.get('type', '') or '').lower()
        is_reel = product == 'clips' or (media == 'video' and product != 'feed')
        items.append({
            'platform': 'instagram',
            'content_type': 'reel' if is_reel else 'post',
            'url': post_url,
            'title': str(post.get('caption', '') or '').strip()[:500],
            'description': '',
            'summary': summary,
            'keywords': _hashtag_names(post.get('hashtags')),
            'published_date': _parse_date(post.get('timestamp')),
        })
    return items


def _fetch_tiktok(client, url, limit):
    run = client.actor(settings.APIFY_TIKTOK_ACTOR).call(
        run_input={
            'profiles': [_tiktok_handle(url)],
            'resultsPerPage': limit,
            'profileSorting': 'latest',
        },
        max_items=limit,
        run_timeout=timedelta(seconds=_ACTOR_TIMEOUT_SECS),
    )
    items = []
    for video in _iterate_dataset(client, run):
        video_url = str(video.get('webVideoUrl', '') or '').strip()
        if not video_url:
            continue
        summary = _engagement([
            _like_str(video.get('playCount'), 'views'),
            _like_str(video.get('diggCount'), 'likes'),
            _like_str(video.get('commentCount'), 'comments'),
        ])
        items.append({
            'platform': 'tiktok',
            'content_type': 'video',
            'url': video_url,
            'title': str(video.get('text', '') or '').strip()[:500],
            'description': '',
            'summary': summary,
            'keywords': _hashtag_names(video.get('hashtags')),
            'published_date': _parse_date(video.get('createTimeISO')),
        })
    return items


def _like_str(count, label):
    n = _fmt(count)
    return f'{n} {label}' if n is not None else None


def fetch(url, platform, label, limit):
    """Fetch recent posts/videos for a social channel.

    Returns (items, status) where status is 'ok' or 'error'. Never raises.
    Only call when is_configured() is True.
    """
    client = _get_client()
    if not client:
        return [], 'error'
    try:
        if platform == 'instagram':
            return _fetch_instagram(client, url, limit), 'ok'
        if platform == 'tiktok':
            return _fetch_tiktok(client, url, limit), 'ok'
        logger.warning('Apify fetch called with unsupported platform %r', platform)
        return [], 'error'
    except Exception:
        logger.warning('Apify %s fetch failed for %s', label, url, exc_info=True)
        return [], 'error'
