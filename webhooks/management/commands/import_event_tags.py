import json
from datetime import date, datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials

from django.conf import settings
from django.core.management.base import BaseCommand

from webhooks.models import EventTag

SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

# gspread may return a Date cell as the displayed string, an ISO string, or a
# raw Google Sheets serial number depending on the cell's type and the sheet's
# locale/format. Tolerate all of them rather than assuming one display format.
_DATE_FORMATS = (
    '%a %b %d %Y',   # Sat Jul 04 2026  (abbreviated month, the common form here)
    '%a %b %d, %Y',  # Sat Jul 04, 2026
    '%a %B %d %Y',   # Sun April 26 2026  (full month name, also seen in this sheet)
    '%a %B %d, %Y',  # Sun April 26, 2026
    '%Y-%m-%d',      # 2026-07-04
    '%m/%d/%Y',      # 07/04/2026
    '%b %d %Y',      # Jul 04 2026
    '%B %d %Y',      # July 04 2026
    '%B %d, %Y',     # July 04, 2026
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


class Command(BaseCommand):
    help = (
        "One-time import of per-event tags from the Google Sheet into the local "
        "EventTag table. Reads worksheet 0 once via GOOGLE_CREDENTIALS_JSON / "
        "GOOGLE_SPREADSHEET_ID and upserts (city, event_date, tag) rows. "
        "Idempotent and re-runnable. Once this has been run in production, the "
        "gspread dependency and the GOOGLE_* settings can be retired."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be imported without writing to the database.',
        )

    def handle(self, *args, **options):
        creds_json = getattr(settings, 'GOOGLE_CREDENTIALS_JSON', '')
        if not creds_json:
            self.stderr.write(self.style.ERROR(
                'import_event_tags: GOOGLE_CREDENTIALS_JSON not set.'
            ))
            return
        spreadsheet_id = getattr(settings, 'GOOGLE_SPREADSHEET_ID', '')
        if not spreadsheet_id:
            self.stderr.write(self.style.ERROR(
                'import_event_tags: GOOGLE_SPREADSHEET_ID not set.'
            ))
            return

        creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
        client = gspread.authorize(creds)
        rows = client.open_by_key(spreadsheet_id).get_worksheet(0).get_all_records()

        dry_run = options.get('dry_run')
        created = existing = skipped = 0
        for row in rows:
            city = str(row.get('Location', '')).strip()
            tag = str(row.get('Tag', '')).strip()
            event_date = _parse_sheet_date(row.get('Date', ''))

            if not city or not tag or event_date is None:
                skipped += 1
                self.stderr.write(self.style.WARNING(
                    f'import_event_tags: skipping row (city={city!r}, '
                    f'date={row.get("Date", "")!r}, tag={tag!r}).'
                ))
                continue

            exists = EventTag.objects.filter(
                city=city, event_date=event_date, tag=tag
            ).exists()
            if exists:
                existing += 1
                continue

            if not dry_run:
                EventTag.objects.create(city=city, event_date=event_date, tag=tag)
            created += 1

        verb = 'would create' if dry_run else 'created'
        self.stdout.write(self.style.SUCCESS(
            f'import_event_tags: {len(rows)} row(s) read; {verb} {created}, '
            f'{existing} already present, {skipped} skipped'
            f"{' [dry run]' if dry_run else ''}."
        ))
