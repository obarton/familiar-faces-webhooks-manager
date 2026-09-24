import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

CITY_TO_MAILCHIMP_TAG = {
    'san francisco': 'Familiar Faces Bay Area',
    'la': 'Familiar Faces LA',
    'los angeles': 'Familiar Faces LA',
    'oakland': 'Familiar Faces Bay Area',
    'phoenix': 'Familiar Faces Phoenix',
    'new york city': 'Familiar Faces NYC',
    'nyc': 'Familiar Faces NYC',
    'san diego': 'Familiar Faces San Diego',
    'seattle': 'Familiar Faces Seattle',
    'vancouver': 'Familiar Faces Vancouver',
    'austin': 'Familiar Faces Austin',
    'portland': 'Familiar Faces Portland',
    'las vegas': 'Familiar Faces Las Vegas',
    'dc': 'Familiar Faces DC',
    'dallas': 'Familiar Faces Dallas'
}


def extract_city(event_name: str) -> str:
    text = event_name.replace(' ', ' ').strip()
    match = re.search(r':\s*([A-Za-zÀ-ÖØ-öø-ÿ .\'-]+)$', text)
    if match:
        return match.group(1).strip()
    match = re.search(r'Familiar Faces\s+([^(]+?)(?:\s*\(.*\))?$', text)
    if match:
        return match.group(1).strip()
    return ''


def get_mailchimp_tag(event_name: str) -> str | None:
    city = extract_city(event_name)
    if not city:
        return None
    return CITY_TO_MAILCHIMP_TAG.get(city.lower())


def get_event_tag(city: str, event_date: date) -> str | None:
    """Per-event tag for (city, event_date), resolved from the local EventTag
    table. Matches city case-insensitively; returns the first non-empty tag."""
    from .models import EventTag
    tag = (
        EventTag.objects
        .filter(city__iexact=city, event_date=event_date)
        .exclude(tag='')
        .values_list('tag', flat=True)
        .first()
    )
    return tag or None
