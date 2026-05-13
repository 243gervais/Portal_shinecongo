from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from sites.models import Location
from .models import IssueReport


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    FINAL_REPORT_NOTIFICATION_EMAIL="mbadunkokorigervais@gmail.com",
    ISSUE_REPORT_NOTIFICATION_EMAIL="mbadunkokorigervais@gmail.com",
)
class EmployeeIssueReportNotificationTests(TestCase):
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
            first_name="Jules",
        )
        self.user.userprofile.role = "EMPLOYE"
        self.user.userprofile.site = self.site
        self.user.userprofile.save()
        self.client.login(username="jules", password="TestPass123!")

    def test_employee_problem_report_sends_admin_email_notification(self):
        response = self.client.post(
            reverse("signaler_probleme"),
            data={
                "categorie": "EAU",
                "description": "Le tuyau d'arrivée fuit près du réservoir.",
            },
        )

        self.assertEqual(response.status_code, 302)
        issue = IssueReport.objects.get(site=self.site, employe=self.user)
        self.assertEqual(issue.statut, "OUVERT")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Problème signalé", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["mbadunkokorigervais@gmail.com"])
        self.assertIn("Employé: Jules", mail.outbox[0].body)
        self.assertIn("Site: Ngaliema Test", mail.outbox[0].body)
        self.assertIn("Catégorie: Eau", mail.outbox[0].body)
        self.assertIn("Le tuyau d'arrivée fuit près du réservoir.", mail.outbox[0].body)
