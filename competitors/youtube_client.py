"""YouTube Data API v3 integration for the competitor content tracker.

Preferred over Firecrawl channel-page scraping for YouTube: the official API
returns each video's exact publish timestamp (plus title, description, and
view/like/comment counts), so dates are accurate and stable instead of guessed
from relative "2 days ago" text. When YOUTUBE_API_KEY is unset, crawl_source
falls back to Firecrawl scraping.

Same fault-tolerance contract as social_client.py / firecrawl_client.py: an
env-var API key read lazily, every network call wrapped so failures log and
return a neutral result. Uses the plain REST endpoints over stdlib urllib, so no
extra dependency or SDK is required.

Quota: refreshing a channel costs ~1–3 units (playlistItems.list + videos.list
per 50 videos); the one-time channel resolution is 1 unit for /channel, /@handle
and /user URLs, or 100 for a /c/custom URL that must go through search.list. The
resolved uploads playlist is cached on the source so recurring refreshes never
repeat the lookup. The free tier is 10,000 units/day.
"""
import json
import logging
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

# Reuse the tolerant date parser and engagement-string helpers already written
# for the other providers (published_date, "1,234 views · 56 likes").
from .firecrawl_client import _parse_date
from .social_client import _engagement, _fmt

logger = logging.getLogger(__name__)

_API_ROOT = 'https://www.googleapis.com/youtube/v3'
_HTTP_TIMEOUT_SECS = 20
_PAGE_SIZE = 50  # API max per playlistItems.list / videos.list call.


def is_configured():
    return bool(getattr(settings, 'YOUTUBE_API_KEY', ''))


def _api_get(resource, params):
    """GET a Data API resource and return parsed JSON. Raises on network/HTTP error."""
    query = urlencode({**params, 'key': getattr(settings, 'YOUTUBE_API_KEY', '')})
    req = Request(f'{_API_ROOT}/{resource}?{query}', headers={'Accept': 'application/json'})
    with urlopen(req, timeout=_HTTP_TIMEOUT_SECS) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _count_str(count, label):
    """'1234', 'views' -> '1,234 views'; None if the count is missing."""
    n = _fmt(count)
    return f'{n} {label}' if n is not None else None


def _channel_query(url):
    """Map a channel/handle URL to channels.list params that identify it, or None
    if it needs the search.list fallback (a /c/<custom> or bare name URL)."""
    url = (url or '').strip()
    m = re.search(r'/channel/(UC[\w-]+)', url)
    if m:
        return {'id': m.group(1)}
    m = re.search(r'/@([\w.\-]+)', url)
    if m:
        return {'forHandle': m.group(1)}
    m = re.search(r'/user/([\w.\-]+)', url)
    if m:
        return {'forUsername': m.group(1)}
    return None


def _search_channel_id(url):
    """Last-resort resolution for /c/<custom> or bare-name URLs via search.list
    (100 quota units). Returns a channel id or None."""
    m = re.search(r'/(?:c/)?([\w.\-]+)/?$', (url or '').strip())
    term = m.group(1) if m else (url or '').strip()
    if not term:
        return None
    data = _api_get('search', {'part': 'snippet', 'type': 'channel', 'q': term, 'maxResults': 1})
    items = data.get('items') or []
    return items[0].get('id', {}).get('channelId') if items else None


def _resolve_uploads_playlist(url):
    """Resolve a channel URL to its "uploads" playlist id, or None if not found."""
    params = _channel_query(url)
    if params is None:
        channel_id = _search_channel_id(url)
        if not channel_id:
            return None
        params = {'id': channel_id}
    data = _api_get('channels', {'part': 'contentDetails', **params})
    items = data.get('items') or []
    if not items:
        return None
    return items[0].get('contentDetails', {}).get('relatedPlaylists', {}).get('uploads') or None


def _uploads_playlist_for(source, url):
    """Return the source's uploads playlist id, resolving and caching it on first use."""
    cached = getattr(source, 'youtube_uploads_playlist', '')
    if cached:
        return cached
    playlist_id = _resolve_uploads_playlist(url)
    if playlist_id and source.pk:
        source.youtube_uploads_playlist = playlist_id
        source.save(update_fields=['youtube_uploads_playlist', 'updated_at'])
    return playlist_id


def _iter_playlist(playlist_id, limit):
    """Yield up to `limit` raw playlistItems, paging the API (50 per page)."""
    fetched = 0
    page_token = None
    while fetched < limit:
        params = {
            'part': 'snippet,contentDetails',
            'playlistId': playlist_id,
            'maxResults': min(_PAGE_SIZE, limit - fetched),
        }
        if page_token:
            params['pageToken'] = page_token
        data = _api_get('playlistItems', params)
        page = data.get('items') or []
        for item in page:
            yield item
            fetched += 1
        page_token = data.get('nextPageToken')
        if not page_token or not page:
            break


def _fetch_statistics(video_ids):
    """Map video id -> statistics dict (viewCount, likeCount, ...) in 50-id batches."""
    stats = {}
    for i in range(0, len(video_ids), _PAGE_SIZE):
        batch = video_ids[i:i + _PAGE_SIZE]
        data = _api_get('videos', {'part': 'statistics', 'id': ','.join(batch)})
        for video in data.get('items') or []:
            stats[video['id']] = video.get('statistics') or {}
    return stats


def _fetch_videos(playlist_id, limit):
    """Build content-item dicts for a channel's most recent `limit` videos."""
    raw = list(_iter_playlist(playlist_id, limit))
    video_ids = [
        item['contentDetails']['videoId']
        for item in raw
        if (item.get('contentDetails') or {}).get('videoId')
    ]
    stats = _fetch_statistics(video_ids) if video_ids else {}

    items = []
    for item in raw:
        details = item.get('contentDetails') or {}
        snippet = item.get('snippet') or {}
        video_id = details.get('videoId')
        if not video_id:
            continue
        # videoPublishedAt is the true upload time; snippet.publishedAt (added to
        # the uploads playlist) is an identical fallback for regular uploads.
        published = details.get('videoPublishedAt') or snippet.get('publishedAt')
        stat = stats.get(video_id, {})
        summary = _engagement([
            _count_str(stat.get('viewCount'), 'views'),
            _count_str(stat.get('likeCount'), 'likes'),
            _count_str(stat.get('commentCount'), 'comments'),
        ])
        items.append({
            'platform': 'youtube',
            'content_type': 'video',
            'url': f'https://www.youtube.com/watch?v={video_id}',
            'title': str(snippet.get('title', '') or '').strip()[:500],
            'description': str(snippet.get('description', '') or '').strip(),
            'summary': summary,
            'keywords': [],
            'published_date': _parse_date(published),
        })
    return items


def fetch(source, url, label, limit):
    """Fetch recent videos for a YouTube channel via the Data API.

    Returns (items, status) where status is 'ok' or 'error'. Never raises.
    Only call when is_configured() is True.
    """
    if not is_configured():
        return [], 'error'
    try:
        playlist_id = _uploads_playlist_for(source, url)
        if not playlist_id:
            logger.warning('YouTube: could not resolve channel for %s (%s)', label, url)
            return [], 'error'
        return _fetch_videos(playlist_id, limit), 'ok'
    except (HTTPError, URLError) as exc:
        logger.warning('YouTube Data API request failed for %s (%s): %s', label, url, exc)
        return [], 'error'
    except Exception:
        logger.warning('YouTube Data API fetch failed for %s (%s)', label, url, exc_info=True)
        return [], 'error'
