import json
import logging
import re
from datetime import date, datetime, timedelta

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


# gspread may return a Date cell as the displayed string, an ISO string, or a
# raw Google Sheets serial number depending on the cell's type and the sheet's
# locale/format. Tolerate all of them rather than assuming one display format.
_DATE_FORMATS = (
    '%a %b %d %Y',   # Sat Jul 04 2026  (displayed format in this sheet)
    '%a %b %d, %Y',  # Sat Jul 04, 2026
    '%Y-%m-%d',      # 2026-07-04
    '%m/%d/%Y',      # 07/04/2026
    '%b %d %Y',      # Jul 04 2026
    '%B %d %Y',      # July 04 2026
)

# Google Sheets serial dates count days from 1899-12-30.
_SHEETS_EPOCH = date(1899, 12, 30)


def _parse_sheet_date(value) -> date | None:
    if value in (None, ''):
        return None
    # Serial number (cell stored as a real date but returned unformatted).
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and value.replace('.', '', 1).isdigit()
    ):
        try:
            return _SHEETS_EPOCH + timedelta(days=int(float(value)))
        except (ValueError, OverflowError):
            return None
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def get_event_tag(city: str, event_date: date) -> str | None:
    client = _get_client()
    if not client:
        logger.warning(
            'Event tag lookup skipped: Google Sheets client unavailable '
            '(GOOGLE_CREDENTIALS_JSON not set or invalid). city=%r date=%s',
            city, event_date,
        )
        return None

    spreadsheet_id = getattr(settings, 'GOOGLE_SPREADSHEET_ID', '')
    if not spreadsheet_id:
        logger.warning(
            'Event tag lookup skipped: GOOGLE_SPREADSHEET_ID not set. city=%r date=%s',
            city, event_date,
        )
        return None

    try:
        sh = client.open_by_key(spreadsheet_id)
        ws = sh.get_worksheet(0)
        rows = ws.get_all_records()

        location_matches = 0
        seen_dates = []
        for row in rows:
            location = str(row.get('Location', '')).strip()
            raw_date = row.get('Date', '')
            tag = str(row.get('Tag', '')).strip()

            if location.lower() != city.lower():
                continue
            location_matches += 1

            row_date = _parse_sheet_date(raw_date)
            if row_date is None:
                seen_dates.append(repr(raw_date))
                logger.warning(
                    'Event tag: row matched location %r but could not parse '
                    'Date cell %r', city, raw_date,
                )
                continue
            seen_dates.append(row_date.isoformat())

            if row_date == event_date:
                if tag:
                    return tag
                logger.warning(
                    'Event tag: matched row for city=%r date=%s but its Tag cell is empty',
                    city, event_date,
                )
                return None

        if location_matches:
            logger.warning(
                'Event tag: found %d row(s) for city=%r but none matched date=%s; '
                'saw dates=%s', location_matches, city, event_date, seen_dates,
            )
        else:
            logger.warning(
                'Event tag: no rows in sheet matched Location=%r (checked %d rows)',
                city, len(rows),
            )
        return None
    except Exception:
        logger.warning('Google Sheets lookup failed', exc_info=True)
        return None
