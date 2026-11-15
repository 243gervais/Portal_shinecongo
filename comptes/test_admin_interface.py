from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from sites.models import Location


class AdminInterfaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_superuser('interface_owner', 'owner@example.test', 'test-password')
        cls.site = Location.objects.create(nom='Centre test')
        cls.employee = User.objects.create_user('interface_employee', password='test-password')
        profile = cls.employee.userprofile
        profile.site = cls.site
        profile.save()

    def test_all_admin_sections_render_with_shared_navigation(self):
        self.client.force_login(self.owner)
        pages = [
            ('admin_dashboard', []), ('admin_messages', []),
            ('admin_daily_report_history', []), ('admin_water_purchases', []),
            ('admin_fuel_purchases', []), ('admin_password_management', []),
            ('admin_site_detail', [self.site.pk]),
            ('admin_site_attendance_photos', [self.site.pk]),
            ('admin_site_documents', [self.site.pk]),
            ('admin_site_employees', [self.site.pk]),
            ('admin_site_journal', [self.site.pk]),
            ('admin_create_site', []),
            ('mobilewash_dashboard', []), ('mobilewash_companies', []),
            ('mobilewash_contracts', []), ('mobilewash_vehicles', []),
            ('mobilewash_schedules', []), ('mobilewash_work_orders', []),
        ]
        for name, args in pages:
            with self.subTest(page=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="admin-portal"')
                self.assertContains(response, 'aria-label="Navigation administration"')
                self.assertNotContains(response, 'fonts.googleapis.com')

    def test_contextual_navigation_and_active_section(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('admin_site_employees', args=[self.site.pk]))
        self.assertContains(response, f'href="{reverse("admin_site_employees", args=[self.site.pk])}" aria-current="page"')
        self.assertContains(response, reverse('admin_site_detail', args=[self.site.pk]))

    def test_employee_and_login_do_not_receive_admin_shell(self):
        for user, name in ((None, 'login'), (self.employee, 'employe_dashboard')):
            if user:
                self.client.force_login(user)
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'class="admin-portal"')
            self.assertNotContains(response, 'aria-label="Navigation administration"')

    def test_native_admin_lists_forms_and_logout(self):
        self.client.force_login(self.owner)
        for name in ('admin:index', 'admin:auth_user_changelist', 'admin:auth_user_add'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'css/django-admin.css')
                self.assertContains(response, 'id="logout-form" method="post"')
                self.assertNotContains(response, 'fonts.googleapis.com')
        response = self.client.post(reverse('admin:logout'))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)
