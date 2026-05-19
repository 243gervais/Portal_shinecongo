from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlparse

from comptes.forms import ApprovalAuthenticationForm
from comptes.views import _daily_funding_snapshot
from comptes.models import AdminReminder, EmployeePayment
from lavages.models import CarWash
from sites.models import Location, SiteDocument, SiteJournalEntry, SiteWaterPurchase
from sites.models import DailyBankDeposit, SiteLossEntry
from pointage.models import ShiftDay
from problemes.models import IssueReport


TEST_GIF_BYTES = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
    b"\x00\x00\x00\xff\xff\xff!\xf9\x04\x01"
    b"\x00\x00\x00\x00,\x00\x00\x00\x00\x01"
    b"\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


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
        self.assertContains(response, "Messages")
        self.assertNotContains(response, "Django Admin")
        self.assertContains(response, "Recherche admin ou site")
        self.assertContains(response, "Convertisseur USD/FC")
        self.assertContains(response, "Pilotage hebdomadaire")
        self.assertContains(response, "Demandes de comptes en attente")
        self.assertContains(response, "Mini convertisseur")
        self.assertContains(response, "window.instantNavigate")
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


class AdminReminderDashboardTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="reminder_admin",
            email="reminder_admin@example.com",
            password="AdminPass123!",
        )
        self.site = Location.objects.create(
            nom="Site Rappels",
            adresse="Adresse Rappels",
            ville="Kinshasa",
            actif=True,
        )
        self.employee = User.objects.create_user(
            username="birthday_employee",
            email="birthday_employee@example.com",
            password="EmployeePass123!",
            first_name="Mike",
            last_name="Mwana-Ntambwe",
        )
        self.employee.userprofile.role = "EMPLOYE"
        self.employee.userprofile.site = self.site
        self.employee.userprofile.actif = True
        self.employee.userprofile.date_naissance = timezone.localdate() + timedelta(days=5)
        self.employee.userprofile.save()
        self.client.login(username="reminder_admin", password="AdminPass123!")

    def test_messages_page_shows_admin_reminders_and_upcoming_birthdays(self):
        AdminReminder.objects.create(
            title="Mettre à jour shinecongo.org",
            description="Publier les nouvelles photos sur le site principal.",
            target="WEBSITE",
            priority="IMPORTANT",
            due_at=timezone.now() + timedelta(days=2),
            created_by=self.admin_user,
        )

        response = self.client.get(reverse("admin_messages"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Messages & notifications")
        self.assertContains(response, "shinecongo.org")
        self.assertContains(response, "Mettre à jour shinecongo.org")
        self.assertContains(response, "Anniversaires à venir")
        self.assertContains(response, "Mike Mwana-Ntambwe")

    def test_admin_can_create_reminder_from_messages_page(self):
        due_at = timezone.localtime(timezone.now() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(
            reverse("admin_messages"),
            data={
                "action": "create_admin_reminder",
                "target": "PORTAL",
                "priority": "URGENT",
                "title": "Vérifier le portail avant lundi",
                "description": "Contrôler les messages et les rapports en attente.",
                "due_at": due_at,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            reverse('admin_messages'),
            fetch_redirect_response=False,
        )
        reminder = AdminReminder.objects.get(title="Vérifier le portail avant lundi")
        self.assertEqual(reminder.target, "PORTAL")
        self.assertEqual(reminder.priority, "URGENT")
        self.assertEqual(reminder.created_by, self.admin_user)

    def test_admin_can_resolve_reminder(self):
        reminder = AdminReminder.objects.create(
            title="Relire la page d'accueil",
            target="WEBSITE",
            priority="INFO",
            created_by=self.admin_user,
        )

        response = self.client.post(reverse("admin_resolve_reminder", args=[reminder.id]))

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            reverse('admin_messages'),
            fetch_redirect_response=False,
        )
        reminder.refresh_from_db()
        self.assertTrue(reminder.is_resolved)
        self.assertIsNotNone(reminder.resolved_at)


class AdminPasswordManagementTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="password_admin",
            email="password_admin@example.com",
            password="AdminPass123!",
        )
        self.site = Location.objects.create(
            nom="Site Passwords",
            adresse="Adresse Passwords",
            ville="Kinshasa",
            actif=True,
        )
        self.manager_user = User.objects.create_user(
            username="manager_portal",
            email="manager@example.com",
            password="ManagerPass123!",
            is_active=True,
        )
        self.manager_user.userprofile.role = "MANAGER"
        self.manager_user.userprofile.site = self.site
        self.manager_user.userprofile.actif = True
        self.manager_user.userprofile.save()
        self.employee_user = User.objects.create_user(
            username="employee_portal",
            email="employee_portal@example.com",
            password="EmployeePass123!",
            is_active=True,
        )
        self.employee_user.userprofile.role = "EMPLOYE"
        self.employee_user.userprofile.site = self.site
        self.employee_user.userprofile.actif = True
        self.employee_user.userprofile.save()
        self.client.login(username="password_admin", password="AdminPass123!")

    def test_admin_dashboard_links_to_password_management(self):
        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestion des mots de passe")
        self.assertContains(response, reverse("admin_password_management"))

    def test_admin_can_open_password_management_page(self):
        response = self.client.get(reverse("admin_password_management"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestion des mots de passe")
        self.assertContains(response, "Mon compte")
        self.assertContains(response, "employee_portal")
        self.assertContains(response, "manager_portal")
        self.assertContains(response, "Site Passwords")

    def test_admin_can_change_employee_password(self):
        response = self.client.post(
            reverse("admin_change_user_password", args=[self.employee_user.id]),
            data={
                "new_password1": "FreshEmployeePass456!",
                "new_password2": "FreshEmployeePass456!",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("admin_password_management"), fetch_redirect_response=False)
        self.employee_user.refresh_from_db()
        self.assertTrue(self.employee_user.check_password("FreshEmployeePass456!"))

        self.client.logout()
        self.assertTrue(self.client.login(username="employee_portal", password="FreshEmployeePass456!"))

    def test_admin_can_change_own_password_and_stay_logged_in(self):
        response = self.client.post(
            reverse("admin_change_user_password", args=[self.admin_user.id]),
            data={
                "new_password1": "FreshAdminPass456!",
                "new_password2": "FreshAdminPass456!",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("admin_password_management"), fetch_redirect_response=False)
        self.admin_user.refresh_from_db()
        self.assertTrue(self.admin_user.check_password("FreshAdminPass456!"))

        follow_up = self.client.get(reverse("admin_password_management"))
        self.assertEqual(follow_up.status_code, 200)
        self.assertContains(follow_up, "Gestion des mots de passe")


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

    def test_admin_can_rename_site_document_from_library(self):
        document = SiteDocument.objects.create(
            site=self.site,
            file_type="PHOTO_CONSTRUCTION",
            title="Photo chantier A",
            description="Avant renommage",
            file=SimpleUploadedFile("chantier-a.jpg", b"fake-image-content", content_type="image/jpeg"),
            uploaded_by=self.admin_user,
        )

        library_response = self.client.get(reverse("admin_site_documents", args=[self.site.id]))
        self.assertEqual(library_response.status_code, 200)
        self.assertContains(
            library_response,
            reverse("admin_edit_site_document", args=[self.site.id, document.id]),
        )
        self.assertContains(library_response, "Renommer")

        response = self.client.post(
            reverse("admin_edit_site_document", args=[self.site.id, document.id]),
            data={
                "title": "Photo chantier renommée",
                "next": reverse("admin_site_documents", args=[self.site.id]),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            reverse("admin_site_documents", args=[self.site.id]),
            fetch_redirect_response=False,
        )
        document.refresh_from_db()
        self.assertEqual(document.title, "Photo chantier renommée")

    def test_site_documents_page_is_documents_only(self):
        response = self.client.get(reverse("admin_site_documents", args=[self.site.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bibliothèque documentaire")
        self.assertContains(response, "Gestion des employés")
        self.assertNotContains(response, "Vue équipe")
        self.assertNotContains(response, "Historique des paiements")


class EmployeePaymentShareTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="payment_admin",
            email="payment_admin@example.com",
            password="AdminPass123!",
        )
        self.site = Location.objects.create(
            nom="Site Paiement",
            adresse="Adresse Paiement",
            ville="Kinshasa",
            actif=True,
        )
        self.employee = User.objects.create_user(
            username="employee_payment",
            email="employee_payment@example.com",
            password="EmployeePass123!",
            first_name="Jules",
            last_name="Mbadu",
        )
        self.employee.userprofile.role = "EMPLOYE"
        self.employee.userprofile.site = self.site
        self.employee.userprofile.save()
        self.payment = EmployeePayment.objects.create(
            employee_profile=self.employee.userprofile,
            site=self.site,
            payment_date=date(2026, 4, 20),
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 15),
            salary_base_usd=Decimal("110.00"),
            amount_paid_usd=Decimal("110.00"),
            payment_method="MPESA",
            mpesa_reference="MPESA-123",
            employee_signature_name="Jules Mbadu",
            admin_signature_name="Gervais",
            created_by=self.admin_user,
        )
        self.client.login(username="payment_admin", password="AdminPass123!")

    def test_payment_receipt_view_displays_share_actions(self):
        response = self.client.get(
            reverse("admin_employee_payment_receipt", args=[self.site.id, self.payment.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Partager le PDF")
        self.assertContains(response, "WhatsApp Web (PDF)")
        self.assertContains(response, "Télécharger le PDF")
        self.assertIn("share_pdf_url", response.context)
        self.assertContains(response, response.context["share_pdf_url"])

    def test_shared_payment_receipt_view_is_accessible_without_login(self):
        response = self.client.get(
            reverse("admin_employee_payment_receipt", args=[self.site.id, self.payment.id])
        )
        share_path = urlparse(response.context["share_url"]).path

        self.client.logout()
        shared_response = self.client.get(share_path)

        self.assertEqual(shared_response.status_code, 200)
        self.assertContains(shared_response, "FICHE DE PAIEMENT")
        self.assertContains(shared_response, "Jules Mbadu")
        self.assertContains(shared_response, "WhatsApp Web (PDF)")

    def test_shared_payment_receipt_pdf_view_returns_pdf(self):
        response = self.client.get(
            reverse("admin_employee_payment_receipt", args=[self.site.id, self.payment.id])
        )
        share_path = urlparse(response.context["share_pdf_url"]).path

        self.client.logout()
        shared_pdf_response = self.client.get(share_path)

        self.assertEqual(shared_pdf_response.status_code, 200)
        self.assertEqual(shared_pdf_response["Content-Type"], "application/pdf")

    def test_employee_management_page_shows_payment_share_actions(self):
        response = self.client.get(reverse("admin_site_employees", args=[self.site.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestion des employés")
        self.assertContains(response, 'data-tab-trigger="team"')
        self.assertContains(response, 'data-tab-trigger="payments"')
        self.assertContains(response, 'data-tab-trigger="performance"')
        self.assertContains(response, "Partager PDF")
        self.assertContains(response, "WhatsApp Web (PDF)")
        self.assertContains(response, "data-share-pdf-url")

    def test_employee_management_page_keeps_requested_tab(self):
        response = self.client.get(
            reverse("admin_site_employees", args=[self.site.id]),
            {"tab": "payments", "employee": str(self.employee.userprofile.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "payments")
        self.assertContains(response, 'name="tab" value="payments"')


@override_settings(MEDIA_ROOT="/private/tmp/portal_shinecongo_test_media")
class AdminSiteEmployeeFormTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="employee_admin",
            email="employee_admin@example.com",
            password="AdminPass123!",
        )
        self.site = Location.objects.create(
            nom="Site Employes",
            adresse="Adresse Employes",
            ville="Kinshasa",
            actif=True,
        )
        self.client.login(username="employee_admin", password="AdminPass123!")

    def test_admin_employee_form_shows_optional_photo_field(self):
        response = self.client.get(reverse("admin_add_site_employee", args=[self.site.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Photo de l'employé")
        self.assertContains(response, "Optionnel. Ajoutez une photo")
        self.assertContains(response, 'enctype="multipart/form-data"', html=False)

    def test_admin_can_create_employee_with_optional_photo(self):
        response = self.client.post(
            reverse("admin_add_site_employee", args=[self.site.id]),
            data={
                "username": "mike_photo",
                "first_name": "Mike",
                "last_name": "Mwana-Ntambwe",
                "email": "mike.photo@example.com",
                "telephone": "0999999999",
                "mpesa_numero": "243999999999",
                "date_embauche": "2026-05-19",
                "salaire_mensuel_usd": "110.00",
                "password": "EmployeePass123!",
                "is_active": "on",
                "profile_photo": SimpleUploadedFile(
                    "employee.gif",
                    TEST_GIF_BYTES,
                    content_type="image/gif",
                ),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            reverse("admin_site_employees", args=[self.site.id]),
            fetch_redirect_response=False,
        )
        employee = User.objects.get(username="mike_photo")
        employee.userprofile.refresh_from_db()
        self.assertTrue(employee.userprofile.profile_photo.name.endswith(".gif"))


class SiteJournalEntryTests(TestCase):
    def setUp(self):
        rate_data = {
            "usd_to_cdf": "2300",
            "source_date": timezone.localdate().isoformat(),
            "provider": "test-suite",
        }
        cache.set(f"fx:usd_to_cdf:{timezone.localdate().isoformat()}", rate_data, 3600)
        cache.set("fx:usd_to_cdf:last", rate_data, 3600)
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

    def test_site_journal_form_displays_fc_and_usd_amount_fields(self):
        response = self.client.get(reverse("admin_site_journal", args=[self.site.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Montant lié (FC)")
        self.assertContains(response, "Montant lié (USD)")
        self.assertContains(response, "1 USD = 2 300 FC")

    def test_admin_can_create_site_journal_entry(self):
        reminder_at = timezone.localtime(timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(
            reverse("admin_site_journal", args=[self.site.id]),
            data={
                "entry_date": "2026-04-11",
                "category": "DEPENSE",
                "title": "Achat matériel supplémentaire",
                "description": "Achat urgent de matériel pour le site.",
                "amount_fc": "25000",
                "reminder_at": reminder_at,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            f"{reverse('admin_site_journal', args=[self.site.id])}?month=2026-04",
            fetch_redirect_response=False,
        )
        entry = SiteJournalEntry.objects.get(site=self.site)
        self.assertEqual(entry.title, "Achat matériel supplémentaire")
        self.assertEqual(entry.amount_fc, Decimal("25000"))
        self.assertEqual(entry.created_by, self.admin_user)
        self.assertEqual(entry.reminder_email, "journal_admin@example.com")
        self.assertIsNotNone(entry.reminder_at)
        self.assertIsNone(entry.reminder_sent_at)

    def test_admin_can_create_site_journal_entry_from_usd_amount(self):
        response = self.client.post(
            reverse("admin_site_journal", args=[self.site.id]),
            data={
                "entry_date": "2026-04-12",
                "category": "DEPENSE",
                "title": "Achat payé en dollars",
                "description": "Paiement saisi directement en USD.",
                "amount_fc": "",
                "amount_usd": "10",
                "reminder_at": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        entry = SiteJournalEntry.objects.get(site=self.site, title="Achat payé en dollars")
        self.assertEqual(entry.amount_fc, Decimal("23000.00"))

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

    def test_site_detail_buttons_preserve_selected_day_context(self):
        response = self.client.get(
            reverse("admin_site_detail", args=[self.site.id]),
            data={"date_debut": "2026-04-11", "date_fin": "2026-04-11"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f"{reverse('admin_add_wash', args=[self.site.id])}?date=2026-04-11&next=",
            html=False,
        )
        self.assertContains(
            response,
            f"{reverse('admin_add_daily_total', args=[self.site.id])}?date=2026-04-11&next=",
            html=False,
        )
        self.assertContains(
            response,
            f"{reverse('admin_add_bank_deposit', args=[self.site.id])}?date=2026-04-11&next=",
            html=False,
        )

    def test_site_detail_single_day_journal_shows_full_day_activity_details(self):
        employee = User.objects.create_user(
            username="daily_employee",
            email="daily_employee@example.com",
            password="EmployeePass123!",
            first_name="Jules",
            last_name="Mbadu",
        )
        employee.userprofile.role = "EMPLOYE"
        employee.userprofile.site = self.site
        employee.userprofile.save()

        CarWash.objects.create(
            employe=employee,
            site=self.site,
            date=date(2026, 4, 11),
            type_service="COMPLET",
            plaque="ABC123",
            montant=Decimal("28000.00"),
            notes="Client habituel",
        )
        DailyBankDeposit.objects.create(
            site=self.site,
            date=date(2026, 4, 11),
            amount=Decimal("36000.00"),
            notes="Depot principal de la journee",
            created_by=self.admin_user,
        )
        SiteLossEntry.objects.create(
            site=self.site,
            date=date(2026, 4, 11),
            category="TRANSPORT",
            funding_source="CAISSE",
            amount=Decimal("24000.00"),
            title="Transport équipe",
            description="Navette du personnel",
            created_by=self.admin_user,
        )
        ShiftDay.objects.create(
            employe=employee,
            site=self.site,
            date=date(2026, 4, 11),
            clock_in_time=timezone.make_aware(datetime(2026, 4, 11, 8, 0)),
            clock_out_time=timezone.make_aware(datetime(2026, 4, 11, 18, 15)),
            daily_report_confirmed=True,
            total_lavages_reported=3,
            total_amount_reported_fc=Decimal("60000.00"),
            daily_expenses=[
                {
                    "key": "transport_personnels",
                    "label": "Transport de Personnels",
                    "amount_fc": "24000",
                    "is_known": True,
                }
            ],
            daily_expenses_total_fc=Decimal("24000.00"),
            report_notes="Le reste a ete mis a la banque.",
        )
        SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 4, 1),
            purchase_date=date(2026, 4, 11),
            amount_fc=Decimal("22000.00"),
            notes="Remplissage du tank",
            created_by=self.admin_user,
        )
        SiteJournalEntry.objects.create(
            site=self.site,
            entry_date=date(2026, 4, 11),
            category="INFO",
            title="Visite du bailleur",
            description="Passage pour verifier le site.",
            created_by=self.admin_user,
        )
        issue = IssueReport.objects.create(
            employe=employee,
            site=self.site,
            categorie="CLIENT",
            description="Client difficile sur site.",
            statut="OUVERT",
        )
        IssueReport.objects.filter(id=issue.id).update(
            created_at=timezone.make_aware(datetime(2026, 4, 11, 14, 30)),
            updated_at=timezone.make_aware(datetime(2026, 4, 11, 14, 30)),
        )

        response = self.client.get(
            reverse("admin_site_detail", args=[self.site.id]),
            data={"date_debut": "2026-04-11", "date_fin": "2026-04-11"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Journal complet de la journee")
        self.assertContains(response, "Lavages enregistres")
        self.assertContains(response, "Flux financiers du jour")
        self.assertContains(response, "Gestion de l'eau")
        self.assertContains(response, "Notes et suivi du site")
        self.assertContains(response, "Problemes et observations du jour")
        self.assertContains(response, "Presences et pointages")
        self.assertContains(response, "ABC123")
        self.assertContains(response, "Transport équipe")
        self.assertContains(response, "Depot principal de la journee")
        self.assertContains(response, "Remplissage du tank")
        self.assertContains(response, "Visite du bailleur")
        self.assertContains(response, "Client difficile sur site.")
        self.assertContains(response, "Transport de Personnels")
        self.assertGreaterEqual(len(response.context["single_day_activity_entries"]), 6)

    def test_site_detail_month_view_shows_full_period_finance_details(self):
        employee = User.objects.create_user(
            username="period_employee",
            email="period_employee@example.com",
            password="EmployeePass123!",
        )
        employee.userprofile.role = "EMPLOYE"
        employee.userprofile.site = self.site
        employee.userprofile.save()

        CarWash.objects.create(
            employe=employee,
            site=self.site,
            date=date(2026, 4, 11),
            type_service="COMPLET",
            plaque="ABC123",
            montant=Decimal("75000.00"),
        )
        DailyBankDeposit.objects.create(
            site=self.site,
            date=date(2026, 4, 11),
            amount=Decimal("50000.00"),
            notes="Depot du 11 avril",
            created_by=self.admin_user,
        )
        SiteLossEntry.objects.create(
            site=self.site,
            date=date(2026, 4, 11),
            category="TRANSPORT",
            funding_source="CAISSE",
            amount=Decimal("14000.00"),
            title="Transport équipe",
            description="Navette du personnel",
            created_by=self.admin_user,
        )
        ShiftDay.objects.create(
            employe=employee,
            site=self.site,
            date=date(2026, 4, 11),
            clock_in_time=timezone.now(),
            clock_out_time=timezone.now(),
            daily_report_confirmed=True,
            total_lavages_reported=4,
            total_amount_reported_fc=Decimal("75000.00"),
            daily_expenses_total_fc=Decimal("14000.00"),
        )
        SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 4, 1),
            purchase_date=date(2026, 4, 12),
            amount_fc=Decimal("22000.00"),
            notes="Remplissage du tank",
            created_by=self.admin_user,
        )
        SiteJournalEntry.objects.create(
            site=self.site,
            entry_date=date(2026, 4, 14),
            category="DEPENSE",
            title="Achat de matériel",
            description="Achat de nouveaux accessoires",
            amount_fc=Decimal("12000.00"),
            created_by=self.admin_user,
        )
        issue = IssueReport.objects.create(
            employe=employee,
            site=self.site,
            categorie="EAU",
            description="Le tuyau principal fuit près du réservoir.",
            statut="OUVERT",
        )
        IssueReport.objects.filter(id=issue.id).update(
            created_at=timezone.make_aware(datetime(2026, 4, 15, 10, 0)),
            updated_at=timezone.make_aware(datetime(2026, 4, 15, 10, 0)),
        )

        response = self.client.get(
            reverse("admin_site_detail", args=[self.site.id]),
            data={"date_debut": "2026-04-01", "date_fin": "2026-04-30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lecture complète de la période")
        self.assertContains(response, "Dépôts banque période")
        self.assertContains(response, "Banque nette période")
        self.assertContains(response, "Journal quotidien de la période")
        self.assertContains(response, "Dépôts bancaires de la période")
        self.assertContains(response, "Pertes et dépenses de la période")
        self.assertContains(response, "Rapports employés, eau, problèmes et journal du site")
        self.assertContains(response, "50 000 FC")
        self.assertContains(response, "14 000 FC")
        self.assertContains(response, "22 000 FC")
        self.assertContains(response, "Transport équipe")
        self.assertContains(response, "Achat de matériel")
        self.assertContains(response, "Problèmes signalés")
        self.assertContains(response, "Problèmes: 1 • Eau: 1 • Journal: 1")
        self.assertContains(response, "Le tuyau principal fuit près du réservoir.")
        self.assertContains(response, 'href="#historique-lavages"')
        self.assertContains(response, 'href="#period-bank-deposits"')
        self.assertContains(response, 'href="#period-losses"')
        self.assertContains(response, 'href="#period-reports"')
        self.assertContains(response, 'href="#period-activity-stream"')
        self.assertTrue(response.context["show_period_breakdown"])
        self.assertEqual(response.context["period_bank_deposit_total"], Decimal("50000"))
        self.assertEqual(response.context["period_losses_total"], Decimal("14000"))
        self.assertEqual(response.context["period_water_count"], 1)

    def test_site_journal_breaks_down_selected_month_by_category(self):
        SiteJournalEntry.objects.create(
            site=self.site,
            entry_date=date(2026, 4, 11),
            category="DEPENSE",
            title="Achat matériel supplémentaire",
            description="Achat urgent de matériel pour le site.",
            amount_fc=Decimal("25000"),
            created_by=self.admin_user,
        )
        SiteJournalEntry.objects.create(
            site=self.site,
            entry_date=date(2026, 4, 14),
            category="INFO",
            title="Visite du bailleur",
            description="Passage sur site pour validation.",
            created_by=self.admin_user,
        )
        SiteJournalEntry.objects.create(
            site=self.site,
            entry_date=date(2026, 3, 28),
            category="INTERVENTION",
            title="Intervention mars",
            description="Réparation antérieure.",
            amount_fc=Decimal("12000"),
            created_by=self.admin_user,
        )

        response = self.client.get(
            reverse("admin_site_journal", args=[self.site.id]),
            data={"month": "2026-04"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_month_input"], "2026-04")
        self.assertContains(response, "Dépenses / avances")
        self.assertContains(response, "Achat matériel supplémentaire")
        self.assertContains(response, "Visite du bailleur")
        self.assertNotContains(response, "Intervention mars")
        self.assertContains(response, 'href="#journal-category-depense"', html=False)
        self.assertContains(response, 'href="#journal-category-info"', html=False)
        self.assertContains(response, 'id="journal-category-depense"', html=False)
        self.assertContains(response, 'id="journal-category-info"', html=False)

        selected_month_data = response.context["selected_month_data"]
        self.assertEqual(selected_month_data["expense_total"], Decimal("25000"))
        categories = {item["code"]: item for item in selected_month_data["categories"]}
        self.assertEqual(categories["DEPENSE"]["entries_count"], 1)
        self.assertEqual(categories["INFO"]["entries_count"], 1)
        self.assertEqual(categories["INTERVENTION"]["entries_count"], 0)

    def test_admin_can_move_site_journal_entry_to_new_category_and_month(self):
        entry = SiteJournalEntry.objects.create(
            site=self.site,
            entry_date=date(2026, 4, 18),
            category="INFO",
            title="Information mal classée",
            description="Cette note devait être en dépense.",
            amount_fc=Decimal("18000"),
            created_by=self.admin_user,
        )

        response = self.client.post(
            f"{reverse('admin_move_site_journal_entry', args=[self.site.id, entry.id])}?month=2026-04",
            data={
                "entry_date": "2026-05-02",
                "category": "DEPENSE",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            f"{reverse('admin_site_journal', args=[self.site.id])}?month=2026-05#journal-category-depense",
            fetch_redirect_response=False,
        )

        entry.refresh_from_db()
        self.assertEqual(entry.entry_date, date(2026, 5, 2))
        self.assertEqual(entry.category, "DEPENSE")

        moved_response = self.client.get(
            reverse("admin_site_journal", args=[self.site.id]),
            data={"month": "2026-05"},
        )
        self.assertContains(moved_response, "Information mal classée")
        self.assertContains(moved_response, "Migrer")


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

    def test_water_purchase_page_uses_new_rate_for_may_2026(self):
        response = self.client.get(reverse("admin_water_purchases"), data={"month": "2026-05"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["default_amount"], Decimal("22000"))
        self.assertEqual(response.context["form"].fields["amount_fc"].initial, Decimal("22000"))
        self.assertContains(response, "Depuis le 01/05/2026")
        self.assertContains(response, "22 000 FC")

    def test_water_purchase_page_keeps_old_rate_for_april_2026(self):
        response = self.client.get(reverse("admin_water_purchases"), data={"month": "2026-04"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["default_amount"], Decimal("24000"))
        self.assertEqual(response.context["form"].fields["amount_fc"].initial, Decimal("24000"))
        self.assertContains(response, "24 000 FC")

    def test_water_purchase_view_filters_by_selected_billing_month(self):
        SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 3, 1),
            purchase_date=date(2026, 4, 2),
            amount_fc=Decimal("24000"),
            notes="Note Mars spéciale",
            created_by=self.admin_user,
        )
        SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 4, 1),
            purchase_date=date(2026, 4, 13),
            amount_fc=Decimal("48000"),
            notes="Note Avril spéciale",
            created_by=self.admin_user,
        )

        response = self.client.get(reverse("admin_water_purchases"), data={"month": "2026-03"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Note Mars spéciale")
        self.assertNotContains(response, "Note Avril spéciale")
        self.assertContains(response, "24 000")

    def test_water_purchase_view_shows_weekly_breakdown_for_selected_month(self):
        SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 4, 1),
            purchase_date=date(2026, 4, 2),
            amount_fc=Decimal("24000"),
            notes="Semaine 1 - premier achat",
            created_by=self.admin_user,
        )
        SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 4, 1),
            purchase_date=date(2026, 4, 4),
            amount_fc=Decimal("24000"),
            notes="Semaine 1 - second achat",
            created_by=self.admin_user,
        )
        SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 4, 1),
            purchase_date=date(2026, 4, 15),
            amount_fc=Decimal("24000"),
            notes="Semaine 3 - achat",
            created_by=self.admin_user,
        )

        response = self.client.get(reverse("admin_water_purchases"), data={"month": "2026-04"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rythme hebdomadaire du mois")
        self.assertContains(response, "Semaine du 01/04 au 05/04")
        self.assertContains(response, "Semaine du 13/04 au 19/04")
        self.assertContains(response, "2 achats enregistrés pour cette semaine")
        self.assertContains(response, "1 achat enregistré pour cette semaine")
        self.assertEqual(response.context["weekly_breakdown"][0]["count"], 2)
        self.assertEqual(response.context["weekly_breakdown"][0]["total"], Decimal("48000"))
        self.assertEqual(response.context["weekly_breakdown"][2]["count"], 1)


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


class SiteHistoryComparisonTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="history_admin",
            email="history_admin@example.com",
            password="AdminPass123!",
        )
        self.site = Location.objects.create(
            nom="Site Historique",
            adresse="Adresse Historique",
            ville="Kinshasa",
            actif=True,
        )
        self.client.login(username="history_admin", password="AdminPass123!")

        CarWash.objects.create(
            employe=self.admin_user,
            site=self.site,
            date=date(2026, 4, 21),
            type_service="COMPLET",
            montant=Decimal("10000"),
        )
        DailyBankDeposit.objects.create(site=self.site, date=date(2026, 4, 21), amount=Decimal("7000"))
        SiteLossEntry.objects.create(
            site=self.site,
            date=date(2026, 4, 21),
            funding_source="CAISSE",
            category="AUTRE",
            amount=Decimal("2000"),
            title="Transport semaine active",
        )
        ShiftDay.objects.create(
            employe=self.admin_user,
            site=self.site,
            date=date(2026, 4, 21),
            daily_report_confirmed=True,
            total_amount_reported_fc=Decimal("9500"),
        )

        CarWash.objects.create(
            employe=self.admin_user,
            site=self.site,
            date=date(2026, 3, 10),
            type_service="COMPLET",
            montant=Decimal("25000"),
        )
        DailyBankDeposit.objects.create(site=self.site, date=date(2026, 3, 10), amount=Decimal("16000"))
        SiteLossEntry.objects.create(
            site=self.site,
            date=date(2026, 3, 10),
            funding_source="BANQUE",
            category="AUTRE",
            amount=Decimal("3000"),
            title="Achat banque mars",
        )

        CarWash.objects.create(
            employe=self.admin_user,
            site=self.site,
            date=date(2025, 12, 15),
            type_service="COMPLET",
            montant=Decimal("40000"),
        )
        DailyBankDeposit.objects.create(site=self.site, date=date(2025, 12, 15), amount=Decimal("30000"))

    def test_history_comparison_page_renders_selected_scope(self):
        response = self.client.get(
            reverse("admin_site_history_comparison", args=[self.site.id]),
            data={"scope": "month", "date": "2026-04-21"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Historique comparatif")
        self.assertContains(response, "Hebdomadaire")
        self.assertContains(response, "Mensuel")
        self.assertContains(response, "Annuel")
        self.assertContains(response, "Prévision")
        self.assertContains(response, "Avril 2026")
        self.assertContains(response, "Mars 2026")
        self.assertEqual(response.context["current_scope"], "month")
        self.assertEqual(response.context["selected_period"]["key"], "month")

    def test_site_detail_links_to_history_comparison_page(self):
        response = self.client.get(reverse("admin_site_detail", args=[self.site.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ouvrir la page complète")
        self.assertContains(response, reverse("admin_site_history_comparison", args=[self.site.id]))


class AdminDailyReportHistoryTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="report_admin",
            email="report_admin@example.com",
            password="AdminPass123!",
        )
        self.site_a = Location.objects.create(
            nom="Ngolomingo",
            adresse="Avenue A",
            ville="Kinshasa",
            actif=True,
        )
        self.site_b = Location.objects.create(
            nom="Bandal",
            adresse="Avenue B",
            ville="Kinshasa",
            actif=True,
        )
        self.employee_a = User.objects.create_user(
            username="mike_history",
            email="mike_history@example.com",
            password="EmployeePass123!",
        )
        self.employee_b = User.objects.create_user(
            username="jules_history",
            email="jules_history@example.com",
            password="EmployeePass123!",
        )
        self.employee_a.userprofile.role = "EMPLOYE"
        self.employee_a.userprofile.site = self.site_a
        self.employee_a.userprofile.save()
        self.employee_b.userprofile.role = "EMPLOYE"
        self.employee_b.userprofile.site = self.site_b
        self.employee_b.userprofile.save()
        self.client.login(username="report_admin", password="AdminPass123!")

        ShiftDay.objects.create(
            employe=self.employee_a,
            site=self.site_a,
            date=date(2026, 4, 24),
            daily_report_confirmed=True,
            total_amount_reported_fc=Decimal("25000.00"),
            total_lavages_reported=3,
            daily_expenses=[
                {
                    "key": "transport_personnels",
                    "label": "Transport de Personnels",
                    "amount_fc": "14000.00",
                    "is_known": True,
                }
            ],
            daily_expenses_total_fc=Decimal("14000.00"),
        )
        ShiftDay.objects.create(
            employe=self.employee_b,
            site=self.site_b,
            date=date(2026, 4, 25),
            daily_report_confirmed=True,
            total_amount_reported_fc=Decimal("18000.00"),
            total_lavages_reported=2,
            daily_expenses=[
                {
                    "key": "transport_personnels",
                    "label": "Transport de Personnels",
                    "amount_fc": "9000.00",
                    "is_known": True,
                }
            ],
            daily_expenses_total_fc=Decimal("9000.00"),
        )
        ShiftDay.objects.create(
            employe=self.employee_a,
            site=self.site_a,
            date=date(2026, 3, 18),
            daily_report_confirmed=True,
            total_amount_reported_fc=Decimal("30000.00"),
            total_lavages_reported=4,
            daily_expenses_total_fc=Decimal("11000.00"),
        )

    def test_daily_report_history_page_renders_selected_month(self):
        response = self.client.get(
            reverse("admin_daily_report_history"),
            data={"month": "2026-04"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Historique des rapports")
        self.assertContains(response, "Avril 2026")
        self.assertContains(response, "mike_history")
        self.assertContains(response, "jules_history")
        self.assertContains(response, "25 000")
        self.assertContains(response, "18 000")
        self.assertEqual(response.context["selected_month_input"], "2026-04")
        self.assertEqual(response.context["month_summary"]["report_count"], 2)

    def test_daily_report_history_page_filters_by_site(self):
        response = self.client.get(
            reverse("admin_daily_report_history"),
            data={"month": "2026-04", "site": str(self.site_a.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mike_history")
        self.assertEqual(response.context["selected_site"], self.site_a)
        self.assertEqual(response.context["month_summary"]["report_count"], 1)
        self.assertEqual(len(response.context["daily_groups"]), 1)
        self.assertEqual(response.context["daily_groups"][0]["entries"][0]["employee_name"], "mike_history")

    def test_admin_dashboard_links_to_daily_report_history_page(self):
        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Voir l'historique complet")
        self.assertContains(response, reverse("admin_daily_report_history"))


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
