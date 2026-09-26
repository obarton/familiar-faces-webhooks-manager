from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

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


class EventTagUITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='owen', password='pw')
        self.client.force_login(self.user)

    def test_login_required(self):
        self.client.logout()
        resp = self.client.get(reverse('webhooks:tag_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.url)

    def test_list_shows_tag(self):
        EventTag.objects.create(city='Oakland', event_date=date(2026, 7, 4), tag='FF_OAK')
        resp = self.client.get(reverse('webhooks:tag_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'FF_OAK')

    def test_city_filter_narrows_results(self):
        EventTag.objects.create(city='Oakland', event_date=date(2026, 7, 4), tag='FF_OAK')
        EventTag.objects.create(city='Seattle', event_date=date(2026, 7, 5), tag='FF_SEA')
        resp = self.client.get(reverse('webhooks:tag_list'), {'city': 'Oakland'})
        self.assertContains(resp, 'FF_OAK')
        self.assertNotContains(resp, 'FF_SEA')

    def test_blank_city_filter(self):
        EventTag.objects.create(city='', event_date=date(2026, 7, 4), tag='FF_BLANK')
        EventTag.objects.create(city='Seattle', event_date=date(2026, 7, 5), tag='FF_SEA')
        resp = self.client.get(reverse('webhooks:tag_list'), {'city': '__none__'})
        self.assertContains(resp, 'FF_BLANK')
        self.assertNotContains(resp, 'FF_SEA')

    def test_pagination(self):
        for i in range(30):
            EventTag.objects.create(city='Oakland', event_date=date(2026, 1, 1), tag=f'T{i}')
        resp = self.client.get(reverse('webhooks:tag_list'))
        self.assertEqual(len(resp.context['page_obj'].object_list), 25)
        self.assertEqual(resp.context['page_obj'].paginator.num_pages, 2)

    def test_create_page_shows_new_tag_labels(self):
        # EventTag.id has a UUID default, so form.instance.pk is truthy even for
        # a new instance; the create page must still read as "New Tag".
        resp = self.client.get(reverse('webhooks:tag_create'))
        self.assertContains(resp, 'Create Tag')
        self.assertNotContains(resp, 'Save changes')

    def test_edit_page_shows_edit_labels(self):
        tag = EventTag.objects.create(city='LA', event_date=date(2026, 9, 26), tag='FF_LA')
        resp = self.client.get(reverse('webhooks:tag_edit', args=[tag.id]))
        self.assertContains(resp, 'Save changes')
        self.assertNotContains(resp, 'Create Tag')

    def test_create(self):
        resp = self.client.post(reverse('webhooks:tag_create'), {
            'city': 'Portland', 'event_date': '2026-08-01', 'tag': 'FF_PDX',
        })
        self.assertRedirects(resp, reverse('webhooks:tag_list'))
        self.assertTrue(EventTag.objects.filter(city='Portland', tag='FF_PDX').exists())

    def test_edit_prefills_and_updates(self):
        tag = EventTag.objects.create(city='LA', event_date=date(2026, 9, 26), tag='FF_LA')
        url = reverse('webhooks:tag_edit', args=[tag.id])
        get_resp = self.client.get(url)
        # HTML5 date input pre-fills with the ISO value.
        self.assertContains(get_resp, 'value="2026-09-26"')
        post_resp = self.client.post(url, {
            'city': 'LA', 'event_date': '2026-09-26', 'tag': 'FF_LA_UPDATED',
        })
        self.assertRedirects(post_resp, reverse('webhooks:tag_list'))
        tag.refresh_from_db()
        self.assertEqual(tag.tag, 'FF_LA_UPDATED')

    def test_delete(self):
        tag = EventTag.objects.create(city='DC', event_date=date(2026, 9, 5), tag='FF_DC')
        resp = self.client.post(reverse('webhooks:tag_delete', args=[tag.id]))
        self.assertRedirects(resp, reverse('webhooks:tag_list'))
        self.assertFalse(EventTag.objects.filter(id=tag.id).exists())
