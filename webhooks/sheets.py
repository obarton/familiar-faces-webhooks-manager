import json
import logging
import re
from datetime import date, datetime

import gspread
from google.oauth2.service_account import Credentials

from django.conf import settings

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

_client = None

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
    text = event_name.replace(' ', ' ').strip()
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


def _get_client():
    global _client
    if _client is not None:
        return _client
    creds_json = getattr(settings, 'GOOGLE_CREDENTIALS_JSON', '')
    if not creds_json:
        return None
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    _client = gspread.authorize(creds)
    return _client


def get_event_tag(city: str, event_date: date) -> str | None:
    client = _get_client()
    if not client:
        return None

    spreadsheet_id = getattr(settings, 'GOOGLE_SPREADSHEET_ID', '')
    if not spreadsheet_id:
        return None

    try:
        sh = client.open_by_key(spreadsheet_id)
        ws = sh.get_worksheet(0)
        rows = ws.get_all_records()

        for row in rows:
            location = str(row.get('Location', '')).strip()
            date_str = str(row.get('Date', '')).strip()
            tag = str(row.get('Tag', '')).strip()

            if location.lower() != city.lower():
                continue

            try:
                row_date = datetime.strptime(date_str, '%a %b %d %Y').date()
            except ValueError:
                continue

            if row_date == event_date:
                return tag or None

        return None
    except Exception:
        logger.warning('Google Sheets lookup failed', exc_info=True)
        return None
