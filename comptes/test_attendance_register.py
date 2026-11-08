from datetime import date, datetime, time
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from comptes.attendance_register import month_register
from comptes.models import UserProfile
from pointage.models import ShiftDay
from sites.models import Location


class AttendanceRegisterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.site = Location.objects.create(nom='Site Centre')
        cls.other_site = Location.objects.create(nom='Autre site')
        cls.admin = User.objects.create_superuser('owner', 'owner@example.com', 'TestPass123!')
        cls.employee = User.objects.create_user('associate', first_name='Anne', last_name='Mbala')
        profile = cls.employee.userprofile
        profile.site = cls.site
        profile.role = UserProfile.EMPLOYEE_ROLE
        profile.save()
        User.objects.filter(pk=cls.employee.pk).update(date_joined=timezone.make_aware(datetime(2026, 8, 1)))
        for day, hour, minute, closed in [(1, 9, 15, True), (2, 9, 46, True), (3, 9, 0, False)]:
            target = date(2026, 9, day)
            ShiftDay.objects.create(
                site=cls.site, employe=cls.employee, date=target,
                clock_in_time=timezone.make_aware(datetime.combine(target, time(hour, minute))),
                clock_out_time=timezone.make_aware(datetime.combine(target, time(19, 15))) if closed else None,
            )

    def detail_url(self, site=None, employee=None):
        return reverse('admin_employee_attendance', args=[(site or self.site).pk, (employee or self.employee).pk])

    def test_month_counts_arrivals_lateness_and_open_shifts(self):
        row = month_register(self.site, date(2026, 9, 1), employee_id=self.employee.pk)['rows'][0]
        self.assertEqual(row['present'], 3)
        self.assertEqual(row['late'], 1)
        self.assertEqual(row['on_time'], 2)
        self.assertEqual(row['missing_end'], 1)
        self.assertEqual(row['late_minutes'], 46)
        self.assertEqual(row['days'][1]['status']['code'], 'LATE')
        self.assertEqual(row['hours'], '19h29')

    def test_owner_can_open_name_and_filter_late_days(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.detail_url(), {'month': '2026-09', 'status': 'LATE'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Anne Mbala')
        self.assertContains(response, 'Journal des présences')
        self.assertEqual(len(response.context['days']), 1)
        self.assertContains(response, '46 min')

    def test_register_name_links_to_monthly_history(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_site_attendance_photos', args=[self.site.pk]), {'month': '2026-09'})
        self.assertContains(response, f'{self.detail_url()}?month=2026-09')
        self.assertContains(response, 'Registre du personnel')

    def test_former_employee_keeps_history_without_new_absences(self):
        profile = self.employee.userprofile
        profile.actif = False
        profile.save()
        self.employee.is_active = False
        self.employee.save()
        row = month_register(self.site, date(2026, 9, 1), employee_id=self.employee.pk)['rows'][0]
        self.assertEqual(row['present'], 3)
        self.assertEqual(row['absent'], 0)
        self.assertTrue(row['archived'])
        self.assertEqual(month_register(self.site, date(2026, 10, 1))['rows'], [])
        self.assertEqual(month_register(self.site, date(2026, 10, 1), employee_id=self.employee.pk)['rows'][0]['present'], 0)

    def test_employee_isolation_and_permission_checks(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.detail_url(site=self.other_site), {'month': '2026-09'}).status_code, 404)
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(self.detail_url(), {'month': '2026-09'}).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get(self.detail_url()).status_code, 302)

    def test_bulk_register_uses_constant_query_count(self):
        for index in range(5):
            user = User.objects.create_user(f'washer{index}')
            profile = user.userprofile
            profile.site = self.site
            profile.save()
        with self.assertNumQueries(2):
            register = month_register(self.site, date(2026, 9, 1))
        self.assertEqual(len(register['rows']), 6)

    def test_hire_date_prevents_inventing_absences_before_employment(self):
        profile = self.employee.userprofile
        profile.date_embauche = date(2026, 9, 15)
        profile.save()
        row = month_register(self.site, date(2026, 9, 1), employee_id=self.employee.pk)['rows'][0]
        self.assertEqual(row['days'][9]['status']['code'], 'UNRECORDED')
        self.assertEqual(row['days'][0]['status']['code'], 'PRESENT')

    def test_existing_remote_photo_does_not_block_attendance_save(self):
        storage = Mock()
        field = ShiftDay._meta.get_field('clock_in_photo')
        with patch.object(field, 'storage', storage):
            shift = ShiftDay.objects.get(employe=self.employee, date=date(2026, 9, 1))
            shift.clock_in_photo = 'remote/proof.jpg'
            shift.save()
        storage.exists.assert_not_called()
        storage.open.assert_not_called()
        storage.save.assert_not_called()
