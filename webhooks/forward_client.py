import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

FORWARD_TIMEOUT_SECS = 10

# Hop-by-hop / host-specific headers that must not be relayed to the target —
# they describe the original connection, not the payload, and would corrupt or
# break the forwarded request.
_SKIP_HEADERS = {'host', 'content-length', 'connection', 'accept-encoding'}


def forward_event(endpoint, event):
    """Relay a received event to endpoint.forward_url.

    Returns a short status string for display (e.g. '200 OK', 'HTTP 500',
    'failed'), or None when forwarding is disabled/unconfigured. Never raises —
    a failed relay must not affect the receiver's response.
    """
    url = (endpoint.forward_url or '').strip()
    if not endpoint.forward_enabled or not url:
        return None

    # Empty body → send None so GET/DELETE relays don't imply a body.
    data = event.body.encode('utf-8') or None
    headers = {
        k: v for k, v in event.headers.items()
        if k.lower() not in _SKIP_HEADERS
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=event.method)
    try:
        with urllib.request.urlopen(req, timeout=FORWARD_TIMEOUT_SECS) as resp:
            return f'{resp.status} OK'
    except urllib.error.HTTPError as e:
        logger.warning('Forward to %s returned %s for event %s', url, e.code, event.id)
        return f'HTTP {e.code}'
    except Exception as e:
        logger.warning('Forward to %s failed for event %s: %s', url, event.id, e)
        return 'failed'
