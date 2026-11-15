from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from comptes.site_dashboard import dashboard_context, dashboard_period
from lavages.models import CarWash, CarWashPhoto
from pointage.models import ShiftDay
from problemes.models import IssueReport
from sites.models import Location, DailyBankDeposit, SiteLossEntry


class SiteDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_superuser('dashboard_owner', 'owner@example.test', 'TestPass123!')
        cls.site = Location.objects.create(nom='Centre Ngaliema', adresse='Avenue Kinshasa')
        cls.other = Location.objects.create(nom='Autre site')
        cls.employee = User.objects.create_user('dashboard_washer', first_name='Anne', last_name='Mbala')
        profile = cls.employee.userprofile
        profile.site = cls.site
        profile.date_embauche = date(2026, 1, 1)
        profile.save()
        cls.day = date(2026, 10, 12)
        CarWash.objects.create(site=cls.site, employe=cls.employee, date=cls.day, montant=Decimal('50000'), plaque='TEST123')
        CarWash.objects.create(site=cls.other, employe=cls.employee, date=cls.day, montant=Decimal('999999'), plaque='PRIVATE987')
        DailyBankDeposit.objects.create(site=cls.site, date=cls.day, amount=Decimal('30000'), created_by=cls.owner)
        SiteLossEntry.objects.create(site=cls.site, date=cls.day, amount=Decimal('10000'), funding_source='CAISSE', title='Transport', created_by=cls.owner)
        SiteLossEntry.objects.create(site=cls.site, date=cls.day, amount=Decimal('2000'), funding_source='BANQUE', title='Frais bancaires', created_by=cls.owner)
        ShiftDay.objects.create(site=cls.site, employe=cls.employee, date=cls.day, daily_report_confirmed=True, total_amount_reported_fc=Decimal('50000'))

    def setUp(self):
        self.client.force_login(self.owner)
        self.url = reverse('admin_site_detail', args=[self.site.pk])
        self.params = {'date_debut': '2026-10-12', 'date_fin': '2026-10-12'}

    def test_overview_preserves_financial_definitions_and_site_isolation(self):
        response = self.client.get(self.url, self.params)
        self.assertTemplateUsed(response, 'admin/site_dashboard.html')
        self.assertEqual(response.context['chiffre_periode'], Decimal('50000'))
        self.assertEqual(response.context['deposits_total'], Decimal('30000'))
        self.assertEqual(response.context['cash_expenses'], Decimal('10000'))
        self.assertEqual(response.context['cash_balance'], Decimal('10000'))
        self.assertEqual(response.context['bank_net'], Decimal('28000'))
        self.assertEqual(response.context['report_variance'], Decimal('0'))
        self.assertContains(response, 'TEST123')
        self.assertNotContains(response, 'PRIVATE987')

    def test_overview_never_builds_legacy_comparisons_or_fetches_exchange_rates(self):
        with (
            patch('comptes.views._build_site_comparison_periods', side_effect=AssertionError('expensive history')),
            patch('shinecongo.currency._fetch_live_usd_to_cdf', side_effect=AssertionError('remote FX')),
        ):
            response = self.client.get(self.url, self.params)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'fonts.googleapis.com')

    def test_large_history_is_bounded_and_query_count_does_not_grow(self):
        request = RequestFactory().get(self.url, self.params)
        with CaptureQueriesContext(connection) as before:
            first = dashboard_context(request, self.site)
        CarWash.objects.bulk_create([CarWash(site=self.site, employe=self.employee, date=self.day, montant=Decimal('1'), plaque=f'BULK{i}') for i in range(150)])
        with CaptureQueriesContext(connection) as after:
            second = dashboard_context(request, self.site)
        self.assertLessEqual(len(after), 16)
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(second['recent_washes']), 6)
        self.assertEqual(second['total_lavages'], first['total_lavages'] + 150)
        response = self.client.get(self.url, {**self.params, 'tab': 'washes', 'washes_page': 2})
        self.assertEqual(len(response.context['wash_page']), 20)
        self.assertEqual(response.context['wash_page'].number, 2)
        self.assertContains(response, 'washes_page=3')

    def test_photo_prefetch_is_limited_per_wash(self):
        wash = CarWash.objects.filter(site=self.site).first()
        CarWashPhoto.objects.bulk_create([CarWashPhoto(lavage=wash, photo=f'test-proof-{i}.jpg') for i in range(30)])
        context = dashboard_context(RequestFactory().get(self.url, self.params), self.site)
        self.assertEqual(len(context['recent_washes'][0].dashboard_photos), 1)
        self.assertEqual(context['recent_washes'][0].photo_count_value, 30)

    def test_focused_views_render_and_keep_selected_dates(self):
        for tab in ('washes', 'finance', 'photos', 'issues'):
            response = self.client.get(self.url, {**self.params, 'tab': tab})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['start'], self.day)
            self.assertContains(response, 'date_debut=2026-10-12')

    def test_issue_filter_is_scoped_and_paginated(self):
        IssueReport.objects.bulk_create([IssueReport(site=self.site, employe=self.employee, categorie='AUTRE', description=f'Incident {i}', statut='OUVERT') for i in range(25)])
        response = self.client.get(self.url, {**self.params, 'tab': 'issues'})
        self.assertEqual(len(response.context['issues_page']), 15)
        self.assertEqual(response.context['open_issue_count'], 25)

    def test_wash_search_does_not_change_period_financial_totals(self):
        response = self.client.get(self.url, {**self.params, 'tab': 'washes', 'q': 'NOT-A-PLATE'})
        self.assertEqual(response.context['wash_page'].paginator.count, 0)
        self.assertEqual(response.context['chiffre_periode'], Decimal('50000'))
        response = self.client.get(self.url, {**self.params, 'tab': 'washes', 'q': 'TEST123'})
        self.assertEqual(response.context['wash_page'].paginator.count, 1)

    def test_financial_records_with_deleted_authors_still_render(self):
        DailyBankDeposit.objects.filter(site=self.site).update(created_by=None)
        SiteLossEntry.objects.filter(site=self.site).update(created_by=None)
        response = self.client.get(self.url, {**self.params, 'tab': 'finance'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '30 000 FC')

    def test_legacy_records_remain_available(self):
        response = self.client.get(self.url, {**self.params, 'view': 'records'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'admin/site_detail.html')
        self.assertContains(response, 'Journal complet de la journee')

    def test_non_admin_and_anonymous_users_cannot_view_site_finances(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_invalid_reversed_and_future_dates_are_safe(self):
        today = timezone.localdate()
        for params in ({'date_debut': '2026-02-30'}, {'date_debut': '9999-12-31'},
                       {'date_debut': '2026-10-15', 'date_fin': '2026-10-01'}):
            start, end = dashboard_period(RequestFactory().get('/', params), today)
            self.assertLessEqual(start, end)
            self.assertLessEqual(end, today)
