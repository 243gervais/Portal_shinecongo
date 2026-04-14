from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone

from sites.models import Location, SiteJournalEntry


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
)
class SiteJournalReminderCommandTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="reminder_admin",
            email="reminder_admin@example.com",
            password="AdminPass123!",
        )
        self.site = Location.objects.create(
            nom="Site Reminder",
            adresse="Adresse Reminder",
            ville="Kinshasa",
            actif=True,
        )

    def test_command_sends_due_site_journal_reminder(self):
        entry = SiteJournalEntry.objects.create(
            site=self.site,
            entry_date=timezone.localdate(),
            category="SUIVI",
            title="Relancer le fournisseur",
            description="Vérifier la disponibilité du matériel prévu pour demain.",
            reminder_at=timezone.now() - timedelta(minutes=2),
            reminder_email="owner@example.com",
            created_by=self.admin_user,
        )

        call_command("send_site_journal_reminders")

        entry.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Rappel journal du site", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["owner@example.com"])
        self.assertIn("Relancer le fournisseur", mail.outbox[0].body)
        self.assertIsNotNone(entry.reminder_sent_at)

    def test_command_ignores_already_sent_reminders(self):
        SiteJournalEntry.objects.create(
            site=self.site,
            entry_date=timezone.localdate(),
            category="INFO",
            title="Rappel déjà envoyé",
            reminder_at=timezone.now() - timedelta(minutes=10),
            reminder_email="owner@example.com",
            reminder_sent_at=timezone.now() - timedelta(minutes=5),
            created_by=self.admin_user,
        )

        call_command("send_site_journal_reminders")

        self.assertEqual(len(mail.outbox), 0)
