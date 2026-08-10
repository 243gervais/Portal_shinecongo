from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext, override_settings
from django.urls import reverse
from django.utils import timezone

from comptes.models import UserProfile
from lavages.models import CarWash, CarWashPhoto
from pointage.models import ShiftDay
from problemes.models import IssueReport
from sites.models import Location, ManagerManualSettings, SiteFuelPurchase, SiteWaterPurchase


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

    def test_portal_shell_script_url_matches_lazy_chunk_imports(self):
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("manager_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'src="/portal-assets/portal-app.js"', html=False)
        self.assertNotContains(response, "portal-app.js?v=", html=False)

    def test_nested_manager_report_route_serves_react_shell(self):
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("manager_daily_report"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="portal-root"', html=False)
        self.assertContains(response, '"mode": "manager"', html=False)

    def test_nested_manager_operation_routes_serve_react_shell(self):
        self.client.login(username="manager", password="pass1234")

        route_names = [
            "manager_presence",
            "manager_add_lavage",
            "manager_water_purchase",
            "manager_fuel_purchase",
            "manager_manual",
        ]

        for route_name in route_names:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
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

    def test_employee_cannot_access_manager_manual_api(self):
        self.client.login(username="employee", password="pass1234")

        response = self.client.get(reverse("portal_api_manager_manual"))

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
            lavage = CarWash.objects.create(
                employe=self.employee,
                site=self.site,
                date=today,
                type_service="COMPLET",
                plaque=f"KIN{index:03d}",
                montant=Decimal("1500.00"),
            )
            for photo_index in range(3):
                CarWashPhoto.objects.create(
                    lavage=lavage,
                    photo=SimpleUploadedFile(
                        f"lavage-{index}-{photo_index}.jpg",
                        b"not-a-real-image",
                        content_type="image/jpeg",
                    ),
                    type_photo="APRES",
                )
        self.client.login(username="manager", password="pass1234")

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("portal_api_manager_lavages"))

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(captured), 14)
        payload = response.json()
        self.assertEqual(payload["results"][0]["photo_count"], 3)
        self.assertEqual(payload["results"][0]["preview_photo"], "")
        self.assertEqual(payload["results"][0]["plaque_photo_thumbnail_url"], "")

    def test_manager_daily_report_payload_is_capped_for_busy_days(self):
        today = timezone.localdate()
        for index in range(35):
            CarWash.objects.create(
                employe=self.employee,
                site=self.site,
                date=today,
                type_service="COMPLET",
                plaque=f"DAY{index:03d}",
                montant=Decimal("1500.00"),
            )
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("portal_api_manager_report"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_lavages"], 35)
        self.assertEqual(len(payload["today_washes"]), 30)
        self.assertTrue(payload["today_washes_truncated"])
        self.assertEqual(payload["today_washes"][0]["preview_photo"], "")

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

    def test_manager_can_load_own_presence_status(self):
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("portal_api_manager_presence"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["site"]["nom"], self.site.nom)
        self.assertIn("can_clock_in", payload)
        self.assertIn("schedule", payload)

    @patch("portal_api.views.is_workday", return_value=True)
    def test_manager_can_record_own_start_attendance(self, _mock_is_workday):
        self.client.login(username="manager", password="pass1234")
        captured_now = timezone.now()

        response = self.client.post(
            reverse("portal_api_manager_clock_in"),
            data={
                "photo": SimpleUploadedFile(
                    "manager-attendance.gif",
                    b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
                    b"\x00\x00\x00\xff\xff\xff!\xf9\x04\x01"
                    b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01"
                    b"\x00\x01\x00\x00\x02\x02D\x01\x00;",
                    content_type="image/gif",
                ),
                "photo_last_modified": str(int(captured_now.timestamp() * 1000)),
            },
        )

        self.assertEqual(response.status_code, 200)
        shift = ShiftDay.objects.get(employe=self.manager, date=timezone.localdate())
        self.assertEqual(shift.site, self.site)
        self.assertTrue(shift.clock_in_photo.name.endswith(".gif"))
        self.assertIsNotNone(shift.clock_in_time)

    def test_manager_manual_api_returns_french_sections_and_default_targets(self):
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("portal_api_manager_manual"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["title"], "Manuel du Manager")
        self.assertEqual(payload["targets"]["daily"]["display"], "130 000 FC")
        self.assertEqual(payload["targets"]["weekly"]["display"], "845 000 FC")
        self.assertEqual(payload["targets"]["monthly"]["display"], "3 380 000 FC")
        section_titles = [section["title"] for section in payload["sections"]]
        self.assertIn("Vue d'ensemble", section_titles)
        self.assertIn("Machines", section_titles)
        self.assertIn("Fournisseurs", section_titles)
        self.assertIn("Indicateurs Clés de Performance (ICP)", section_titles)
        self.assertIn("Vision de Shine Congo", section_titles)
        self.assertEqual(payload["sample_breakdown"][0], {"label": "4 voitures", "display": "80 000 FC"})
        self.assertTrue(payload["icps"])
        self.assertTrue(payload["machines"])
        self.assertTrue(payload["suppliers"])

    def test_manager_manual_api_uses_admin_editable_targets(self):
        ManagerManualSettings.objects.create(
            daily_target_fc=140000,
            weekly_target_fc=910000,
            monthly_target_fc=3640000,
            car_price_fc=21000,
            two_wheel_price_fc=3000,
            three_wheel_price_fc=5500,
        )
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("portal_api_manager_manual"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["targets"]["daily"]["display"], "140 000 FC")
        self.assertEqual(payload["prices"][0]["display"], "21 000 FC")

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

    def test_admin_can_see_manager_presence_photos_in_pointage_list(self):
        admin = User.objects.create_superuser(username="admin", password="pass1234")
        today = timezone.localdate()
        ShiftDay.objects.create(
            employe=self.manager,
            site=self.site,
            date=today,
            clock_in_time=timezone.now(),
            clock_in_photo=SimpleUploadedFile(
                "manager-start.gif",
                b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
                b"\x00\x00\x00\xff\xff\xff!\xf9\x04\x01"
                b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01"
                b"\x00\x01\x00\x00\x02\x02D\x01\x00;",
                content_type="image/gif",
            ),
        )
        self.client.login(username="admin", password="pass1234")

        response = self.client.get(reverse("portal_api_manager_pointages"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        manager_row = next(item for item in payload["results"] if item["employee_name"] == "manager")
        self.assertIn("manager-start", manager_row["clock_in_photo_url"])
        self.assertTrue(manager_row["clock_in_photo_thumbnail_url"])
        employee_filter_names = [item["nom"] for item in payload["filters"]["employees"]]
        self.assertIn("manager", employee_filter_names)

    def test_location_manager_does_not_see_manager_pointage_rows(self):
        today = timezone.localdate()
        ShiftDay.objects.create(
            employe=self.manager,
            site=self.site,
            date=today,
            clock_in_time=timezone.now(),
        )
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("portal_api_manager_pointages"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["results"], [])
        employee_filter_names = [item["nom"] for item in payload["filters"]["employees"]]
        self.assertNotIn("manager", employee_filter_names)

    def test_admin_can_see_manager_lavage_photo_previews(self):
        admin = User.objects.create_superuser(username="admin", password="pass1234")
        lavage = CarWash.objects.create(
            employe=self.manager,
            site=self.site,
            date=timezone.localdate(),
            type_service="COMPLET",
            plaque="KIN005",
            montant=Decimal("0"),
        )
        CarWashPhoto.objects.create(
            lavage=lavage,
            photo=SimpleUploadedFile(
                "manager-lavage.gif",
                b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
                b"\x00\x00\x00\xff\xff\xff!\xf9\x04\x01"
                b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01"
                b"\x00\x01\x00\x00\x02\x02D\x01\x00;",
                content_type="image/gif",
            ),
            type_photo="APRES",
        )
        self.client.login(username="admin", password="pass1234")

        response = self.client.get(reverse("portal_api_manager_lavages"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["can_view_money"])
        self.assertEqual(payload["results"][0]["employee_name"], "manager")
        self.assertIn("manager-lavage", payload["results"][0]["preview_photo"])
        employee_filter_names = [item["nom"] for item in payload["filters"]["employees"]]
        self.assertIn("manager", employee_filter_names)

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

    def test_location_manager_can_create_lavage_with_photos_without_money(self):
        self.client.login(username="manager", password="pass1234")
        photo = SimpleUploadedFile(
            "lavage.gif",
            b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )

        response = self.client.post(
            reverse("portal_api_manager_lavages"),
            {
                "type_service": "COMPLET",
                "plaque": "KIN777",
                "notes": "Controle manager",
                "photos": photo,
            },
        )

        self.assertEqual(response.status_code, 201)
        lavage = CarWash.objects.get(plaque="KIN777")
        self.assertEqual(lavage.employe, self.manager)
        self.assertEqual(lavage.site, self.site)
        self.assertEqual(lavage.montant, Decimal("0"))
        self.assertEqual(lavage.photos.count(), 1)
        payload = response.json()
        self.assertNotIn("amount_display", payload["lavage"])

    def test_location_manager_can_notify_water_and_fuel(self):
        self.client.login(username="manager", password="pass1234")

        water_response = self.client.post(reverse("portal_api_manager_water"), {})
        fuel_response = self.client.post(reverse("portal_api_manager_fuel"), {"amount_fc": "5000"})

        self.assertEqual(water_response.status_code, 201)
        self.assertEqual(fuel_response.status_code, 201)
        self.assertEqual(SiteWaterPurchase.objects.get().site, self.site)
        fuel_purchase = SiteFuelPurchase.objects.get()
        self.assertEqual(fuel_purchase.site, self.site)
        self.assertEqual(fuel_purchase.amount_fc, Decimal("5000"))
        self.assertEqual(fuel_purchase.created_by, self.manager)

    def test_location_manager_can_send_daily_report_with_total_and_expenses(self):
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
            {
                "notes": "Journee normale.",
                "total_amount_reported_fc": "130000",
                "known_expense_transport_personnels_enabled": "1",
                "known_expense_transport_personnels_amount": "21000",
                "custom_expense_label": ["Eau urgence"],
                "custom_expense_amount": ["5000"],
            },
        )

        self.assertEqual(response.status_code, 200)
        report = ShiftDay.objects.get(employe=self.manager, date=today)
        self.assertTrue(report.daily_report_confirmed)
        self.assertEqual(report.total_lavages_reported, 1)
        self.assertEqual(report.total_amount_reported_fc, Decimal("130000"))
        self.assertEqual(report.daily_expenses_total_fc, Decimal("26000"))
        self.assertEqual(report.daily_expense_items[0]["label"], "Transport de Personnels")
        self.assertEqual(report.daily_expense_items[1]["label"], "Eau urgence")

    def test_location_manager_daily_report_includes_operations_without_lavage_money(self):
        today = timezone.localdate()
        CarWash.objects.create(
            employe=self.manager,
            site=self.site,
            date=today,
            type_service="COMPLET",
            plaque="KIN888",
            montant=Decimal("0"),
        )
        IssueReport.objects.create(
            employe=self.manager,
            site=self.site,
            categorie="MATERIEL",
            description="Pompe lente",
            statut="OUVERT",
        )
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("portal_api_manager_report"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["can_view_money"])
        self.assertEqual(payload["total_lavages"], 1)
        self.assertEqual(payload["issue_count"], 1)
        self.assertEqual(len(payload["today_washes"]), 1)
        self.assertNotIn("amount_display", payload["today_washes"][0])
        self.assertEqual(len(payload["today_issues"]), 1)

    def test_location_manager_daily_report_includes_expenses_and_attendance_rows(self):
        today = timezone.localdate()
        base_time = timezone.now().replace(hour=8, minute=0, second=0, microsecond=0)
        ShiftDay.objects.create(
            employe=self.employee,
            site=self.site,
            date=today,
            clock_in_time=base_time,
            clock_out_time=base_time.replace(hour=17),
        )
        ShiftDay.objects.create(
            employe=self.manager,
            site=self.site,
            date=today,
            clock_in_time=base_time.replace(hour=7, minute=45),
            clock_out_time=base_time.replace(hour=18),
            daily_report_confirmed=True,
            total_amount_reported_fc=Decimal("120000"),
            daily_expenses=[
                {
                    "key": "transport_personnels",
                    "label": "Transport de Personnels",
                    "amount_fc": "21000.00",
                    "is_known": True,
                }
            ],
            daily_expenses_total_fc=Decimal("21000"),
        )
        self.client.login(username="manager", password="pass1234")

        response = self.client.get(reverse("portal_api_manager_report"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["submitted_total_amount"], "120000.00")
        self.assertEqual(payload["expense_form"]["known"][0]["label"], "Transport de Personnels")
        self.assertTrue(payload["expense_form"]["known"][0]["selected"])
        self.assertEqual(payload["attendance_count"], 2)
        attendance_names = [item["employee_name"] for item in payload["attendance_rows"]]
        self.assertIn("employee", attendance_names)
        self.assertIn("manager", attendance_names)
        manager_row = next(item for item in payload["attendance_rows"] if item["username"] == "manager")
        self.assertEqual(manager_row["role_label"], "Manager")
        self.assertEqual(manager_row["clock_out_display"], timezone.localtime(base_time.replace(hour=18)).strftime("%H:%M"))
