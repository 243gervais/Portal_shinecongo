from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from lavages.models import CarWash
from pointage.models import ShiftDay
from sites.models import Location


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    FINAL_REPORT_NOTIFICATION_EMAIL="mbadunkokorigervais@gmail.com",
    DEFAULT_FROM_EMAIL="noreply@shinecongo.org",
)
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

    def test_employee_report_sends_email_notification(self):
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
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Rapport final envoyé", mail.outbox[0].subject)
        self.assertIn("Montant final déclaré: 15,000.00 FC", mail.outbox[0].body)

    def test_employee_can_update_same_day_report_and_second_email_is_sent(self):
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
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Rapport final mis à jour", mail.outbox[0].subject)
        self.assertIn("Montant final déclaré: 17,000.00 FC", mail.outbox[0].body)
