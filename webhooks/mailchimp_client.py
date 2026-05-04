import hashlib
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)


def _api_key():
    return getattr(settings, 'MAILCHIMP_API_KEY', '')


def _list_id():
    return getattr(settings, 'MAILCHIMP_AUDIENCE_ID', '')


def _base_url():
    key = _api_key()
    if not key or '-' not in key:
        return None
    server = key.split('-')[-1]
    return f'https://{server}.api.mailchimp.com/3.0'


def _subscriber_hash(email):
    return hashlib.md5(email.strip().lower().encode()).hexdigest()


def _request(method, path, data=None):
    key = _api_key()
    base = _base_url()
    if not key or not base:
        return None

    url = f'{base}{path}'
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {key}',
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        logger.warning('Mailchimp %s %s returned %s: %s', method, path, e.code, e.read())
        return None
    except Exception:
        logger.warning('Mailchimp request failed', exc_info=True)
        return None


def upsert_subscriber(email, first_name='', last_name='', phone=''):
    list_id = _list_id()
    if not list_id or not email:
        return
    _request('PUT', f'/lists/{list_id}/members/{_subscriber_hash(email)}', {
        'email_address': email,
        'status_if_new': 'subscribed',
        'merge_fields': {
            'FNAME': first_name,
            'LNAME': last_name,
            'PHONE': phone,
        },
    })


def _find_tag(tag_name):
    """Returns the exact tag name from Mailchimp if it exists, else None."""
    list_id = _list_id()
    if not list_id:
        return None
    encoded = urllib.parse.quote(tag_name)
    result = _request('GET', f'/lists/{list_id}/tag-search?name={encoded}')
    if not result:
        return None
    for tag in result.get('tags', []):
        if tag.get('name', '').lower() == tag_name.lower():
            return tag['name']
    return None


def add_tags(email, tag_names):
    """Looks up each tag in Mailchimp and adds matching ones to the subscriber."""
    list_id = _list_id()
    if not list_id or not email or not tag_names:
        return

    found = [{'name': n, 'status': 'active'} for n in tag_names if _find_tag(n)]
    if not found:
        return

    _request('POST', f'/lists/{list_id}/members/{_subscriber_hash(email)}/tags', {'tags': found})
