from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext, override_settings
from django.urls import reverse
from django.utils import timezone

from comptes.models import UserProfile
from lavages.models import CarWash
from pointage.models import ShiftDay
from problemes.models import IssueReport
from sites.models import Location


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PortalShellRoutingTests(TestCase):
    def setUp(self):
        self.site = Location.objects.create(nom="Ngaliema", adresse="Kinshasa", actif=True)
        self.employee = User.objects.create_user(username="employee", password="pass1234")
        self.employee.userprofile.role = UserProfile.EMPLOYEE_ROLE
        self.employee.userprofile.site = self.site
        self.employee.userprofile.actif = True
        self.employee.userprofile.save()
        self.manager = User.objects.create_user(username="manager", password="pass1234")
        self.manager.userprofile.role = UserProfile.MANAGER_ROLE
        self.manager.userprofile.site = self.site
        self.manager.userprofile.actif = True
        self.manager.userprofile.save()

    def test_nested_employee_portal_route_serves_react_shell(self):
        self.client.login(username="employee", password="pass1234")

        response = self.client.get(reverse("mes_lavages"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="portal-root"', html=False)
        self.assertContains(response, '"mode": "employee"', html=False)

    def test_nested_manager_portal_route_serves_react_shell(self):
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("manager_pointages"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="portal-root"', html=False)
        self.assertContains(response, '"mode": "manager"', html=False)

    def test_nested_manager_report_route_serves_react_shell(self):
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("manager_daily_report"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="portal-root"', html=False)
        self.assertContains(response, '"mode": "manager"', html=False)

    def test_unauthenticated_portal_route_redirects_to_login(self):
        response = self.client.get(reverse("manager_lavages"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"))


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PortalApiSecurityAndPaginationTests(TestCase):
    def setUp(self):
        self.site = Location.objects.create(nom="Gombe", adresse="Kinshasa", actif=True)
        self.employee = User.objects.create_user(username="employee", password="pass1234")
        self.employee.userprofile.role = UserProfile.EMPLOYEE_ROLE
        self.employee.userprofile.site = self.site
        self.employee.userprofile.actif = True
        self.employee.userprofile.save()
        self.manager = User.objects.create_user(username="manager", password="pass1234")
        self.manager.userprofile.role = UserProfile.MANAGER_ROLE
        self.manager.userprofile.site = self.site
        self.manager.userprofile.actif = True
        self.manager.userprofile.save()

    def test_employee_list_api_requires_employee_permission(self):
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("portal_api_employee_lavages"))

        self.assertEqual(response.status_code, 403)

    def test_csrf_is_required_for_session_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="employee", password="pass1234")

        response = client.post(
            reverse("portal_api_employee_problemes"),
            data={"categorie": "EAU", "description": "Fuite d'eau"},
        )

        self.assertEqual(response.status_code, 403)

    def test_employee_lavages_are_paginated(self):
        today = timezone.localdate()
        for index in range(15):
            CarWash.objects.create(
                employe=self.employee,
                site=self.site,
                date=today,
                type_service="COMPLET",
                plaque=f"ABC{index:03d}",
                montant=Decimal("1000.00"),
            )
        self.client.login(username="employee", password="pass1234")

        response = self.client.get(reverse("portal_api_employee_lavages"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 15)
        self.assertEqual(payload["page_size"], 12)
        self.assertEqual(len(payload["results"]), 12)
        self.assertTrue(payload["has_next"])

    def test_manager_lavage_list_query_count_stays_bounded(self):
        today = timezone.localdate()
        for index in range(25):
            CarWash.objects.create(
                employe=self.employee,
                site=self.site,
                date=today,
                type_service="COMPLET",
                plaque=f"KIN{index:03d}",
                montant=Decimal("1500.00"),
            )
        self.client.login(username="manager", password="pass1234")

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("portal_api_manager_lavages"))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(captured), 14)

    def test_location_manager_lavage_api_hides_money(self):
        CarWash.objects.create(
            employe=self.employee,
            site=self.site,
            date=timezone.localdate(),
            type_service="COMPLET",
            plaque="KIN001",
            montant=Decimal("1500.00"),
        )
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("portal_api_manager_lavages"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["can_view_money"])
        self.assertEqual(payload["totals"], {"count": 1})
        self.assertNotIn("amount_display", payload["results"][0])
        self.assertNotIn("amount_fc", payload["results"][0])

    def test_location_manager_dashboard_hides_revenue(self):
        CarWash.objects.create(
            employe=self.employee,
            site=self.site,
            date=timezone.localdate(),
            type_service="COMPLET",
            plaque="KIN002",
            montant=Decimal("2000.00"),
        )
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("portal_api_manager_dashboard"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["can_view_money"])
        self.assertNotIn("revenue_display", payload["sites"][0])
        self.assertNotIn("revenue_fc", payload["sites"][0])
        self.assertEqual(payload["sites"][0]["total_lavages"], 1)

    def test_admin_manager_dashboard_can_still_view_revenue(self):
        admin = User.objects.create_superuser(username="admin", password="pass1234")
        CarWash.objects.create(
            employe=self.employee,
            site=self.site,
            date=timezone.localdate(),
            type_service="COMPLET",
            plaque="KIN003",
            montant=Decimal("2500.00"),
        )
        self.client.login(username="admin", password="pass1234")

        response = self.client.get(reverse("portal_api_manager_dashboard"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["can_view_money"])
        self.assertIn("revenue_display", payload["sites"][0])

    def test_location_manager_can_report_problem_for_assigned_site(self):
        self.client.login(username="manager", password="pass1234")

        response = self.client.post(
            reverse("portal_api_manager_problemes"),
            {"categorie": "MATERIEL", "description": "Aspirateur en panne"},
        )

        self.assertEqual(response.status_code, 201)
        issue = IssueReport.objects.get()
        self.assertEqual(issue.site, self.site)
        self.assertEqual(issue.employe, self.manager)

    def test_location_manager_can_send_daily_report_without_money(self):
        today = timezone.localdate()
        CarWash.objects.create(
            employe=self.employee,
            site=self.site,
            date=today,
            type_service="COMPLET",
            plaque="KIN004",
            montant=Decimal("3000.00"),
        )
        self.client.login(username="manager", password="pass1234")

        response = self.client.post(
            reverse("portal_api_manager_report"),
            {"notes": "Journee normale."},
        )

        self.assertEqual(response.status_code, 200)
        report = ShiftDay.objects.get(employe=self.manager, date=today)
        self.assertTrue(report.daily_report_confirmed)
        self.assertEqual(report.total_lavages_reported, 1)
        self.assertEqual(report.total_amount_reported_fc, Decimal("0"))
