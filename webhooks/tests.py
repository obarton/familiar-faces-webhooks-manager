from datetime import date

from django.test import TestCase

from .models import EventTag
from .tags import get_event_tag, get_mailchimp_tag


class GetEventTagTests(TestCase):
    def test_resolves_tag_from_db(self):
        EventTag.objects.create(
            city='San Francisco', event_date=date(2026, 7, 4), tag='FF SF July 4'
        )
        self.assertEqual(
            get_event_tag('San Francisco', date(2026, 7, 4)), 'FF SF July 4'
        )

    def test_city_match_is_case_insensitive(self):
        EventTag.objects.create(
            city='San Francisco', event_date=date(2026, 7, 4), tag='FF SF July 4'
        )
        self.assertEqual(
            get_event_tag('san francisco', date(2026, 7, 4)), 'FF SF July 4'
        )

    def test_no_match_returns_none(self):
        EventTag.objects.create(
            city='San Francisco', event_date=date(2026, 7, 4), tag='FF SF July 4'
        )
        self.assertIsNone(get_event_tag('San Francisco', date(2026, 7, 5)))
        self.assertIsNone(get_event_tag('Oakland', date(2026, 7, 4)))

    def test_empty_tag_is_ignored(self):
        EventTag.objects.create(
            city='San Francisco', event_date=date(2026, 7, 4), tag=''
        )
        self.assertIsNone(get_event_tag('San Francisco', date(2026, 7, 4)))


class GetMailchimpTagTests(TestCase):
    def test_city_maps_to_market_tag(self):
        self.assertEqual(
            get_mailchimp_tag('Familiar Faces: Oakland'), 'Familiar Faces Bay Area'
        )

    def test_unknown_city_returns_none(self):
        self.assertIsNone(get_mailchimp_tag('Familiar Faces: Atlantis'))
