import json
import logging
from datetime import date, datetime

import gspread
from google.oauth2.service_account import Credentials

from django.conf import settings

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

_client = None


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
