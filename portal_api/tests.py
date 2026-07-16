from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext, override_settings
from django.urls import reverse
from django.utils import timezone

from comptes.models import UserProfile
from lavages.models import CarWash
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
