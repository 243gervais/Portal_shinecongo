from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from lavages.models import CarWash
from pointage.models import ShiftDay
from sites.models import Location


class EmployeeDailyReportTests(TestCase):
    def setUp(self):
        self.site = Location.objects.create(
            nom="Ngaliema Test",
            adresse="Avenue Test",
            ville="Kinshasa",
            actif=True,
        )
        self.user = User.objects.create_user(
            username="jules",
            email="jules@example.com",
            password="TestPass123!",
        )
        self.user.userprofile.role = "EMPLOYE"
        self.user.userprofile.site = self.site
        self.user.userprofile.save()
        self.client.login(username="jules", password="TestPass123!")

    def test_employee_report_is_saved(self):
        today = timezone.localdate()
        CarWash.objects.create(
            employe=self.user,
            site=self.site,
            date=today,
            type_service="COMPLET",
            plaque="ABC123",
            montant=Decimal("13000.00"),
        )

        response = self.client.post(
            reverse("employe_daily_report"),
            data={
                "total_amount_reported_fc": "15000",
                "report_notes": "Fin de journée OK",
            },
        )

        self.assertEqual(response.status_code, 302)
        shift = ShiftDay.objects.get(employe=self.user, date=today)
        self.assertTrue(shift.daily_report_confirmed)
        self.assertEqual(shift.total_amount_reported_fc, Decimal("15000"))

    def test_employee_can_update_same_day_report(self):
        today = timezone.localdate()
        ShiftDay.objects.create(
            employe=self.user,
            site=self.site,
            date=today,
            daily_report_confirmed=True,
            total_amount_reported_fc=Decimal("12000.00"),
            total_lavages_reported=1,
            report_notes="Premier envoi",
        )

        response = self.client.post(
            reverse("employe_daily_report"),
            data={
                "total_amount_reported_fc": "17000",
                "report_notes": "Montant corrigé",
            },
        )

        self.assertEqual(response.status_code, 302)
        shift = ShiftDay.objects.get(employe=self.user, date=today)
        self.assertTrue(shift.daily_report_confirmed)
        self.assertEqual(shift.total_amount_reported_fc, Decimal("17000"))
        self.assertEqual(shift.report_notes, "Montant corrigé")


class AdminDashboardDailyReportMessagesTests(TestCase):
    def setUp(self):
        self.site = Location.objects.create(
            nom="Ngaliema Test",
            adresse="Avenue Test",
            ville="Kinshasa",
            actif=True,
        )
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="AdminPass123!",
        )
        self.employee = User.objects.create_user(
            username="mike",
            email="mike@example.com",
            password="TestPass123!",
        )
        self.employee.userprofile.role = "EMPLOYE"
        self.employee.userprofile.site = self.site
        self.employee.userprofile.save()
        self.client.login(username="admin", password="AdminPass123!")

    def test_admin_dashboard_shows_daily_report_message(self):
        today = timezone.localdate()
        ShiftDay.objects.create(
            employe=self.employee,
            site=self.site,
            date=today,
            daily_report_confirmed=True,
            total_amount_reported_fc=Decimal("25000.00"),
            total_lavages_reported=3,
            report_notes="RAS",
        )

        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Boite Admin")
        self.assertContains(response, "Messages - Rapports de fin de journée")
        self.assertContains(response, "mike")
        self.assertContains(response, "25 000")
        self.assertContains(response, "RAS")
        self.admin_user.userprofile.refresh_from_db()
        self.assertIsNotNone(self.admin_user.userprofile.admin_reports_last_seen_at)
