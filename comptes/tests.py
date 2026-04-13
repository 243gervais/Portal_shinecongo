from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from datetime import date
from decimal import Decimal

from comptes.forms import ApprovalAuthenticationForm
from comptes.views import _daily_funding_snapshot
from sites.models import Location, SiteDocument, SiteJournalEntry, SiteWaterPurchase
from sites.models import DailyBankDeposit, SiteLossEntry
from pointage.models import ShiftDay


class AccountApprovalFlowTests(TestCase):
    def test_registration_creates_inactive_account(self):
        site = Location.objects.create(
            nom="Site Test",
            adresse="Adresse Test",
            ville="Kinshasa",
            actif=True,
        )

        response = self.client.post(
            reverse("register"),
            data={
                "username": "pending_user",
                "password1": "testpass1234",
                "password2": "testpass1234",
                "site": str(site.id),
                "telephone": "123456789",
            },
        )

        self.assertRedirects(response, reverse("login"))
        user = User.objects.get(username="pending_user")
        self.assertFalse(user.is_active)
        self.assertFalse(user.userprofile.actif)
        self.assertEqual(user.userprofile.site, site)

    def test_inactive_user_gets_pending_approval_message(self):
        user = User.objects.create_user(
            username="inactive_user",
            password="testpass1234",
            is_active=False,
        )
        form = ApprovalAuthenticationForm(
            request=None,
            data={"username": user.username, "password": "testpass1234"},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("en attente", str(form.non_field_errors()))


class AdminCreateSiteViewTests(TestCase):
    def test_superuser_can_create_site_from_custom_admin_page(self):
        admin_user = User.objects.create_superuser(
            username="portaladmin",
            email="portaladmin@example.com",
            password="AdminPass123!",
        )
        self.client.login(username="portaladmin", password="AdminPass123!")

        response = self.client.post(
            reverse("admin_create_site"),
            data={
                "nom": "Station Test",
                "adresse": "Avenue Test",
                "ville": "Kinshasa",
                "telephone": "0999999999",
                "gps_actif": "",
                "latitude": "",
                "longitude": "",
                "rayon_autorisé_mètres": 50,
                "actif": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        site = Location.objects.get(nom="Station Test")
        self.assertRedirects(response, reverse("admin_site_detail", kwargs={"site_id": site.id}))
        self.assertEqual(site.ville, "Kinshasa")
        self.assertTrue(site.actif)
        self.assertTrue(admin_user.is_superuser)

    def test_non_admin_is_redirected_from_custom_site_creation_page(self):
        user = User.objects.create_user(
            username="employee_user",
            email="employee@example.com",
            password="EmployeePass123!",
        )
        self.client.login(username="employee_user", password="EmployeePass123!")

        response = self.client.get(reverse("admin_create_site"))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("dashboard"), fetch_redirect_response=False)
        self.assertFalse(user.is_superuser)


class AdminAccountRequestsDashboardTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="approval_admin",
            email="approval_admin@example.com",
            password="AdminPass123!",
        )
        self.site = Location.objects.create(
            nom="Site Pending",
            adresse="Adresse Pending",
            ville="Kinshasa",
            actif=True,
        )
        self.pending_user = User.objects.create_user(
            username="pending_candidate",
            email="pending_candidate@example.com",
            password="PendingPass123!",
            is_active=False,
        )
        self.pending_user.userprofile.site = self.site
        self.pending_user.userprofile.telephone = "0800000000"
        self.pending_user.userprofile.actif = False
        self.pending_user.userprofile.save()
        self.client.login(username="approval_admin", password="AdminPass123!")

    def test_dashboard_shows_pending_account_requests(self):
        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Boite Admin")
        self.assertNotContains(response, "Django Admin")
        self.assertContains(response, "Demandes de comptes en attente")
        self.assertContains(response, "pending_candidate")
        self.assertContains(response, "Site Pending")
        self.assertContains(response, "Adresse Pending")
        self.admin_user.userprofile.refresh_from_db()
        self.assertIsNotNone(self.admin_user.userprofile.admin_requests_last_seen_at)
        self.assertIsNotNone(self.admin_user.userprofile.admin_reports_last_seen_at)

    def test_admin_can_approve_pending_account_request(self):
        response = self.client.post(reverse("admin_approve_account_request", args=[self.pending_user.id]))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("admin_dashboard"), fetch_redirect_response=False)
        self.pending_user.refresh_from_db()
        self.assertTrue(self.pending_user.is_active)
        self.assertTrue(self.pending_user.userprofile.actif)

    def test_admin_can_reject_pending_account_request(self):
        response = self.client.post(reverse("admin_reject_account_request", args=[self.pending_user.id]))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("admin_dashboard"), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(id=self.pending_user.id).exists())


class SiteDocumentUploadTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="docs_admin",
            email="docs_admin@example.com",
            password="AdminPass123!",
        )
        self.site = Location.objects.create(
            nom="Site Docs",
            adresse="Adresse Docs",
            ville="Kinshasa",
            actif=True,
        )
        self.client.login(username="docs_admin", password="AdminPass123!")

    def test_multi_file_upload_creates_multiple_documents(self):
        file_1 = SimpleUploadedFile("image1.jpg", b"fake-image-content-1", content_type="image/jpeg")
        file_2 = SimpleUploadedFile("image2.jpg", b"fake-image-content-2", content_type="image/jpeg")

        response = self.client.post(
            reverse("admin_upload_site_document", args=[self.site.id]),
            data={
                "file_type": "PHOTO_CONSTRUCTION",
                "title": "Photos chantier",
                "description": "Serie de photos",
                "file": [file_1, file_2],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            reverse("admin_site_documents", args=[self.site.id]),
            fetch_redirect_response=False,
        )
        self.assertEqual(SiteDocument.objects.filter(site=self.site).count(), 2)
        self.assertTrue(SiteDocument.objects.filter(site=self.site, title="Photos chantier (1)").exists())
        self.assertTrue(SiteDocument.objects.filter(site=self.site, title="Photos chantier (2)").exists())


class SiteJournalEntryTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="journal_admin",
            email="journal_admin@example.com",
            password="AdminPass123!",
        )
        self.site = Location.objects.create(
            nom="Site Journal",
            adresse="Adresse Journal",
            ville="Kinshasa",
            actif=True,
        )
        self.client.login(username="journal_admin", password="AdminPass123!")

    def test_admin_can_create_site_journal_entry(self):
        response = self.client.post(
            reverse("admin_site_journal", args=[self.site.id]),
            data={
                "entry_date": "2026-04-11",
                "category": "DEPENSE",
                "title": "Achat matériel supplémentaire",
                "description": "Achat urgent de matériel pour le site.",
                "amount_fc": "25000",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            reverse("admin_site_journal", args=[self.site.id]),
            fetch_redirect_response=False,
        )
        entry = SiteJournalEntry.objects.get(site=self.site)
        self.assertEqual(entry.title, "Achat matériel supplémentaire")
        self.assertEqual(entry.amount_fc, Decimal("25000"))
        self.assertEqual(entry.created_by, self.admin_user)

    def test_site_detail_shows_journal_preview(self):
        SiteJournalEntry.objects.create(
            site=self.site,
            entry_date=date(2026, 4, 11),
            category="INFO",
            title="Visite du bailleur",
            description="Passage sur site pour validation du prochain chantier.",
            created_by=self.admin_user,
        )

        response = self.client.get(reverse("admin_site_detail", args=[self.site.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Journal du site")
        self.assertContains(response, "Visite du bailleur")
        self.assertContains(response, reverse("admin_site_journal", args=[self.site.id]))


class WaterPurchaseTrackingTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="water_admin",
            email="water_admin@example.com",
            password="AdminPass123!",
        )
        self.site = Location.objects.create(
            nom="Site Eau",
            adresse="Adresse Eau",
            ville="Kinshasa",
            actif=True,
        )
        self.client.login(username="water_admin", password="AdminPass123!")

    def test_admin_can_create_water_purchase(self):
        response = self.client.post(
            reverse("admin_water_purchases"),
            data={
                "site": str(self.site.id),
                "billing_month": "2026-04",
                "purchase_date": "2026-04-13",
                "amount_fc": "24000",
                "notes": "Remplissage du réservoir",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            f"{reverse('admin_water_purchases')}?month=2026-04",
            fetch_redirect_response=False,
        )
        purchase = SiteWaterPurchase.objects.get(site=self.site)
        self.assertEqual(purchase.billing_month, date(2026, 4, 1))
        self.assertEqual(purchase.amount_fc, Decimal("24000"))
        self.assertEqual(purchase.created_by, self.admin_user)

    def test_admin_dashboard_shows_water_purchase_summary(self):
        SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 4, 1),
            purchase_date=timezone.localdate(),
            amount_fc=Decimal("24000"),
            notes="Achat eau du jour",
            created_by=self.admin_user,
        )

        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Achats d'eau")
        self.assertContains(response, "24 000")
        self.assertContains(response, reverse("admin_water_purchases"))

    def test_water_purchase_view_filters_by_selected_billing_month(self):
        SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 3, 1),
            purchase_date=date(2026, 4, 2),
            amount_fc=Decimal("24000"),
            notes="Mars",
            created_by=self.admin_user,
        )
        SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 4, 1),
            purchase_date=date(2026, 4, 13),
            amount_fc=Decimal("48000"),
            notes="Avril",
            created_by=self.admin_user,
        )

        response = self.client.get(reverse("admin_water_purchases"), data={"month": "2026-03"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mars")
        self.assertNotContains(response, "Avril")
        self.assertContains(response, "24 000")


class FundingSnapshotTests(TestCase):
    def test_snapshot_includes_weekly_and_total_bank_balances(self):
        site = Location.objects.create(
            nom="Site Finance",
            adresse="Adresse Finance",
            ville="Kinshasa",
            actif=True,
        )

        DailyBankDeposit.objects.create(site=site, date="2026-03-10", amount=50000)
        DailyBankDeposit.objects.create(site=site, date="2026-03-12", amount=30000)
        DailyBankDeposit.objects.create(site=site, date="2026-03-17", amount=20000)

        SiteLossEntry.objects.create(
            site=site,
            date="2026-03-11",
            funding_source="BANQUE",
            category="AUTRE",
            amount=10000,
            title="Achat semaine",
        )
        SiteLossEntry.objects.create(
            site=site,
            date="2026-03-15",
            funding_source="BANQUE",
            category="AUTRE",
            amount=5000,
            title="Cloture semaine",
        )
        SiteLossEntry.objects.create(
            site=site,
            date="2026-03-18",
            funding_source="BANQUE",
            category="AUTRE",
            amount=7000,
            title="Perte globale",
        )

        snapshot = _daily_funding_snapshot(site, date_obj=date(2026, 3, 15))

        self.assertEqual(snapshot["bank_available"], Decimal("-5000"))
        self.assertEqual(snapshot["bank_week_available"], 65000)
        self.assertEqual(snapshot["bank_total_available"], 65000)


class SiteCorrectionsViewTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="finance_admin",
            email="finance_admin@example.com",
            password="AdminPass123!",
        )
        self.employee = User.objects.create_user(
            username="employee_fix",
            email="employee_fix@example.com",
            password="EmployeePass123!",
        )
        self.site = Location.objects.create(
            nom="Site Correction",
            adresse="Adresse Correction",
            ville="Kinshasa",
            actif=True,
        )
        self.employee.userprofile.site = self.site
        self.employee.userprofile.role = "EMPLOYE"
        self.employee.userprofile.actif = True
        self.employee.userprofile.save()
        ShiftDay.objects.create(
            employe=self.employee,
            site=self.site,
            date=date(2026, 3, 27),
            clock_in_time=timezone.now(),
            daily_report_confirmed=True,
            total_amount_reported_fc=15000,
        )
        self.client.login(username="finance_admin", password="AdminPass123!")

    def test_corrections_page_supports_pointage_metric(self):
        response = self.client.get(
            reverse("admin_site_losses", args=[self.site.id]),
            data={"date": "2026-03-27", "period": "day", "metric": "pointages"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Entrées Pointages")
        self.assertContains(response, "employee_fix")
        self.assertContains(response, "Modifier")
        self.assertContains(response, "Supprimer")
