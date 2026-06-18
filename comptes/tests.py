from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core import mail
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlparse
from urllib.parse import quote
from unittest.mock import patch

from comptes.forms import ApprovalAuthenticationForm
from comptes.recruitment import ReviewedCandidateCV
from comptes.views import _daily_funding_snapshot
from comptes.models import AdminReminder, EmployeePayment, UserProfile
from lavages.models import CarWash
from sites.models import (
    Camera,
    CameraObservation,
    CameraObservationEvidence,
    CameraOperatorDailyReport,
    DailyCameraReport,
    Location,
    SiteDocument,
    SiteJournalEntry,
    SiteWaterPurchase,
    VideoEvidence,
    WaterSupplier,
    get_default_water_supplier,
)
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

    def test_messages_nav_shows_unread_count_until_messages_page_is_opened(self):
        initial_response = self.client.get(reverse("admin_messages"))

        self.assertEqual(initial_response.context["admin_messages_unread_total"], 0)
        self.admin_user.userprofile.refresh_from_db()
        self.assertIsNotNone(self.admin_user.userprofile.admin_messages_last_seen_at)

        self.employee.userprofile.date_naissance = timezone.localdate() + timedelta(days=6)
        self.employee.userprofile.save()
        AdminReminder.objects.create(
            title="Nouvelle note portail",
            target="PORTAL",
            priority="IMPORTANT",
            created_by=self.admin_user,
        )

        dashboard_response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(dashboard_response.context["admin_messages_unread_total"], 2)
        self.assertContains(dashboard_response, "Messages")

        messages_response = self.client.get(reverse("admin_messages"))
        self.assertEqual(messages_response.context["admin_messages_unread_total"], 0)

        dashboard_after_open = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(dashboard_after_open.context["admin_messages_unread_total"], 0)


class DashboardRoleRedirectTests(TestCase):
    def setUp(self):
        self.site = Location.objects.create(
            nom="Site Camera Role",
            adresse="Adresse Camera Role",
            ville="Kinshasa",
            actif=True,
        )

    def test_camera_controller_is_redirected_to_camera_portal(self):
        user = User.objects.create_user(
            username="camera_controller",
            password="CameraPass123!",
        )
        user.userprofile.role = "CONTROLE_CAMERA"
        user.userprofile.site = self.site
        user.userprofile.save()
        self.client.login(username="camera_controller", password="CameraPass123!")

        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, reverse("camera_dashboard"), fetch_redirect_response=False)


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
        self.manager_user.userprofile.password_reference = "ManagerPass123!"
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
        self.employee_user.userprofile.password_reference = "EmployeePass123!"
        self.employee_user.userprofile.save()
        self.admin_user.userprofile.password_reference = "AdminPass123!"
        self.admin_user.userprofile.save()
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
        self.assertContains(response, "Créer un contrôleur caméra")
        self.assertContains(response, "Bloc-notes identifiants")
        self.assertContains(response, "AdminPass123!")
        self.assertContains(response, "EmployeePass123!")
        self.assertContains(response, "ManagerPass123!")
        self.assertContains(response, "Chaque contrôleur caméra doit être assigné à un site")
        self.assertContains(
            response,
            f"{reverse('admin_add_site_employee', args=[self.site.id])}?role=CONTROLE_CAMERA&amp;next={quote(reverse('admin_password_management'))}",
            html=False,
        )

    def test_password_management_links_to_prefilled_camera_controller_form(self):
        response = self.client.get(
            reverse("admin_add_site_employee", args=[self.site.id]),
            {"role": "CONTROLE_CAMERA", "next": reverse("admin_password_management")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["requested_role"], "CONTROLE_CAMERA")
        self.assertEqual(response.context["next_url"], reverse("admin_password_management"))
        self.assertContains(response, "Ajouter un contrôleur caméra")
        self.assertContains(response, "Ce compte sera rattaché au site")
        self.assertContains(response, "Un contrôleur caméra doit toujours être assigné à un site")

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
        self.assertEqual(self.employee_user.userprofile.password_reference, "FreshEmployeePass456!")

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
        self.assertEqual(self.admin_user.userprofile.password_reference, "FreshAdminPass456!")

        follow_up = self.client.get(reverse("admin_password_management"))
        self.assertEqual(follow_up.status_code, 200)
        self.assertContains(follow_up, "Gestion des mots de passe")
        self.assertContains(follow_up, "FreshAdminPass456!")

    def test_admin_can_update_visible_password_memo_without_changing_real_password(self):
        response = self.client.post(
            reverse("admin_update_password_reference", args=[self.employee_user.id]),
            data={"password_reference": "MemoOnlyPass789!"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("admin_password_management"), fetch_redirect_response=False)
        self.employee_user.refresh_from_db()
        self.assertEqual(self.employee_user.userprofile.password_reference, "MemoOnlyPass789!")
        self.assertTrue(self.employee_user.check_password("EmployeePass123!"))

    def test_admin_can_create_camera_controller_and_return_to_password_page(self):
        response = self.client.post(
            reverse("admin_add_site_employee", args=[self.site.id]),
            data={
                "next": reverse("admin_password_management"),
                "role": "CONTROLE_CAMERA",
                "username": "camera_from_passwords",
                "first_name": "Nadia",
                "last_name": "Monitor",
                "email": "nadia.monitor@example.com",
                "telephone": "0888888888",
                "password": "CameraPass123!",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("admin_password_management"), fetch_redirect_response=False)
        created_user = User.objects.get(username="camera_from_passwords")
        self.assertEqual(created_user.userprofile.role, "CONTROLE_CAMERA")
        self.assertEqual(created_user.userprofile.site, self.site)
        self.assertEqual(created_user.userprofile.password_reference, "CameraPass123!")


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

    def test_admin_can_migrate_site_document_to_another_section(self):
        document = SiteDocument.objects.create(
            site=self.site,
            file_type="PHOTO_CONSTRUCTION",
            title="Photo mal classée",
            description="Doit aller dans une autre section.",
            file=SimpleUploadedFile("chantier-b.jpg", b"fake-image-content", content_type="image/jpeg"),
            uploaded_by=self.admin_user,
        )

        library_response = self.client.get(reverse("admin_site_documents", args=[self.site.id]))
        self.assertEqual(library_response.status_code, 200)
        self.assertContains(
            library_response,
            reverse("admin_move_site_document", args=[self.site.id, document.id]),
        )
        self.assertContains(library_response, "Migrer")

        response = self.client.post(
            reverse("admin_move_site_document", args=[self.site.id, document.id]),
            data={
                "file_type": "AUTRE_PHOTO",
                "next": reverse("admin_site_documents", args=[self.site.id]),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            f"{reverse('admin_site_documents', args=[self.site.id])}?type=AUTRE_PHOTO#document-{document.id}",
            fetch_redirect_response=False,
        )

        document.refresh_from_db()
        self.assertEqual(document.file_type, "AUTRE_PHOTO")
        self.assertEqual(document.title, "Photo mal classée")

        destination_response = self.client.get(
            reverse("admin_site_documents", args=[self.site.id]),
            data={"type": "AUTRE_PHOTO"},
        )
        self.assertContains(destination_response, "Photo mal classée")
        self.assertContains(destination_response, "Autre photo")

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
        self.assertContains(response, "CV de l'employé")
        self.assertContains(response, "CV enregistré sur shinecongo.org")
        self.assertContains(response, "Photo de l'employé")
        self.assertContains(response, "Optionnel. Ajoutez une photo")
        self.assertContains(response, 'enctype="multipart/form-data"', html=False)

    def test_admin_can_create_employee_with_optional_photo(self):
        response = self.client.post(
            reverse("admin_add_site_employee", args=[self.site.id]),
            data={
                "role": "EMPLOYE",
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

    @patch("comptes.forms.get_reviewed_candidate_cv_choices")
    @patch("comptes.forms._download_cv_from_url")
    def test_admin_can_create_employee_with_reviewed_shinecongo_cv(self, mock_download_cv, mock_candidates):
        mock_candidates.return_value = [
            ReviewedCandidateCV(
                external_id="15",
                full_name="Jules Mbadu",
                phone="+243896140370",
                city="Kinshasa",
                applied_at=timezone.now(),
                reviewed=True,
                cv_file="cvs/jules-mbadu.pdf",
                cv_url="https://shinecongo.org/media/cvs/jules-mbadu.pdf",
            )
        ]
        mock_download_cv.return_value = ContentFile(b"%PDF-1.4 portal test", name="jules-cv.pdf")

        response = self.client.post(
            reverse("admin_add_site_employee", args=[self.site.id]),
            data={
                "role": "EMPLOYE",
                "username": "jules_cv",
                "first_name": "Jules",
                "last_name": "Mbadu",
                "email": "jules.cv@example.com",
                "telephone": "0999999997",
                "mpesa_numero": "243999999997",
                "date_embauche": "2026-05-20",
                "salaire_mensuel_usd": "130.00",
                "password": "EmployeePass123!",
                "is_active": "on",
                "reviewed_cv_source": "15",
            },
        )

        self.assertEqual(response.status_code, 302)
        employee = User.objects.get(username="jules_cv")
        employee.userprofile.refresh_from_db()
        self.assertTrue(employee.userprofile.cv_file.name.endswith(".pdf"))
        mock_download_cv.assert_called_once_with(
            "https://shinecongo.org/media/cvs/jules-mbadu.pdf",
            "Le CV sélectionné doit provenir de shinecongo.org.",
        )

    @patch("comptes.forms.get_reviewed_candidate_cv_choices")
    @patch("comptes.forms.build_candidate_dossier_pdf")
    def test_admin_can_create_employee_with_generated_candidate_dossier(self, mock_build_dossier, mock_candidates):
        mock_candidates.return_value = [
            ReviewedCandidateCV(
                external_id="18",
                full_name="Mike Mwana-Ntambwe Shabani",
                phone="+243979045624",
                city="Kinshasa",
                applied_at=timezone.now(),
                reviewed=True,
                cv_file="",
                cv_url="",
                education="Licence",
                skills="Gestion, lavage",
                message="Candidat recommandé",
            )
        ]
        mock_build_dossier.return_value = ContentFile(b"%PDF-1.4 generated dossier", name="mike-dossier.pdf")

        response = self.client.post(
            reverse("admin_add_site_employee", args=[self.site.id]),
            data={
                "role": "EMPLOYE",
                "username": "mike_dossier",
                "first_name": "Mike",
                "last_name": "Mwana-Ntambwe",
                "email": "mike.dossier@example.com",
                "telephone": "0999999995",
                "mpesa_numero": "243999999995",
                "date_embauche": "2026-05-22",
                "salaire_mensuel_usd": "120.00",
                "password": "EmployeePass123!",
                "is_active": "on",
                "reviewed_cv_source": "18",
            },
        )

        self.assertEqual(response.status_code, 302)
        employee = User.objects.get(username="mike_dossier")
        employee.userprofile.refresh_from_db()
        self.assertTrue(employee.userprofile.cv_file.name.endswith(".pdf"))
        mock_build_dossier.assert_called_once()

    @patch("comptes.forms.get_reviewed_candidate_cv_choices")
    def test_admin_employee_form_rejects_unknown_reviewed_cv_selection(self, mock_candidates):
        mock_candidates.return_value = [
            ReviewedCandidateCV(
                external_id="15",
                full_name="Jules Mbadu",
                phone="+243896140370",
                city="Kinshasa",
                applied_at=timezone.now(),
                reviewed=True,
                cv_file="cvs/jules-mbadu.pdf",
                cv_url="https://shinecongo.org/media/cvs/jules-mbadu.pdf",
            )
        ]

        response = self.client.post(
            reverse("admin_add_site_employee", args=[self.site.id]),
            data={
                "role": "EMPLOYE",
                "username": "bad_cv_link",
                "first_name": "Bad",
                "last_name": "Link",
                "email": "bad.link@example.com",
                "telephone": "0999999996",
                "mpesa_numero": "243999999996",
                "date_embauche": "2026-05-21",
                "salaire_mensuel_usd": "100.00",
                "password": "EmployeePass123!",
                "is_active": "on",
                "reviewed_cv_source": "404",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("reviewed_cv_source", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="bad_cv_link").exists())

    def test_admin_can_create_camera_controller_account(self):
        response = self.client.post(
            reverse("admin_add_site_employee", args=[self.site.id]),
            data={
                "role": "CONTROLE_CAMERA",
                "username": "camera_staff",
                "first_name": "Grace",
                "last_name": "Kanku",
                "email": "grace.camera@example.com",
                "telephone": "0999999998",
                "mpesa_numero": "243999999998",
                "date_embauche": "2026-05-19",
                "salaire_mensuel_usd": "90.00",
                "password": "CameraPass123!",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            reverse("admin_site_employees", args=[self.site.id]),
            fetch_redirect_response=False,
        )
        camera_staff = User.objects.get(username="camera_staff")
        self.assertEqual(camera_staff.userprofile.role, "CONTROLE_CAMERA")
        self.assertEqual(camera_staff.userprofile.site, self.site)


@override_settings(MEDIA_ROOT="/private/tmp/portal_shinecongo_camera_test_media")
class SiteCameraMonitoringTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="camera_admin",
            email="camera_admin@example.com",
            password="AdminPass123!",
        )
        self.site = Location.objects.create(
            nom="Site Caméras",
            adresse="Adresse Caméras",
            ville="Kinshasa",
            actif=True,
        )
        self.client.login(username="camera_admin", password="AdminPass123!")

    def test_site_detail_links_to_camera_monitoring_workspace(self):
        response = self.client.get(reverse("admin_site_detail", args=[self.site.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Caméras & comptage")
        self.assertContains(response, reverse("admin_site_camera_monitoring", args=[self.site.id]))

    def test_admin_can_create_camera_from_monitoring_page(self):
        response = self.client.post(
            reverse("admin_site_camera_monitoring", args=[self.site.id]),
            data={
                "action": "save_camera",
                "selected_date": "2026-05-21",
                "camera-name": "Entrée principale",
                "camera-camera_number": "1",
                "camera-camera_position": "GATE",
                "camera-app_name": "V380",
                "camera-notes": "Vue principale pour les arrivées.",
                "camera-is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Camera.objects.filter(site=self.site, camera_number=1, name="Entrée principale").exists())

    def test_admin_can_create_daily_camera_report_with_computed_totals(self):
        response = self.client.post(
            reverse("admin_site_camera_monitoring", args=[self.site.id]),
            data={
                "action": "save_daily_camera_report",
                "selected_date": "2026-05-21",
                "report-date": "2026-05-21",
                "report-cars_count": "4",
                "report-motos_count": "3",
                "report-three_wheelers_count": "2",
                "report-notes": "Comptage manuel de la journée.",
            },
        )

        report = DailyCameraReport.objects.get(site=self.site, date=date(2026, 5, 21))
        self.assertRedirects(
            response,
            reverse("admin_site_camera_report_detail", args=[self.site.id, report.id]),
            fetch_redirect_response=False,
        )
        self.assertEqual(report.total_vehicles, 9)
        self.assertEqual(report.expected_revenue, Decimal("79000"))
        self.assertEqual(report.final_cars_count, 4)
        self.assertEqual(report.final_motos_count, 3)
        self.assertEqual(report.final_three_wheelers_count, 2)

    def test_camera_report_detail_can_upload_evidence(self):
        camera = Camera.objects.create(
            site=self.site,
            name="Caméra caisse",
            camera_number=2,
            camera_position="PAYMENT_AREA",
            app_name="Hik Connect",
            is_active=True,
        )
        report = DailyCameraReport.objects.create(
            site=self.site,
            date=date(2026, 5, 21),
            cars_count=2,
            motos_count=1,
            three_wheelers_count=1,
            created_by=self.admin_user,
        )

        response = self.client.post(
            reverse("admin_site_camera_report_detail", args=[self.site.id, report.id]),
            data={
                "action": "upload_video_evidence",
                "evidence-camera": str(camera.id),
                "evidence-title": "Capture caisse matin",
                "evidence-evidence_type": "CAR_COUNT",
                "evidence-clip_date": "2026-05-21",
                "evidence-start_time": "08:15",
                "evidence-end_time": "08:18",
                "evidence-uploaded_file": SimpleUploadedFile(
                    "camera-proof.gif",
                    TEST_GIF_BYTES,
                    content_type="image/gif",
                ),
                "evidence-notes": "Capture de vérification du nombre de véhicules.",
            },
        )

        self.assertEqual(response.status_code, 302)
        evidence = VideoEvidence.objects.get(daily_report=report, camera=camera)
        self.assertEqual(evidence.title, "Capture caisse matin")
        self.assertTrue(evidence.uploaded_file.name.endswith(".gif"))
        self.assertTrue(bool(evidence.s3_url))

        download_response = self.client.get(
            reverse("admin_download_video_evidence", args=[self.site.id, evidence.id])
        )
        self.assertEqual(download_response.status_code, 200)
        self.assertIn("attachment;", download_response["Content-Disposition"])
        self.assertIn(evidence.filename(), download_response["Content-Disposition"])

        detail_response = self.client.get(reverse("admin_site_camera_report_detail", args=[self.site.id, report.id]))
        self.assertContains(detail_response, "Capture caisse matin")
        self.assertContains(detail_response, "Clips & captures du rapport")
        self.assertContains(detail_response, "Motos 3 pneus")
        self.assertContains(detail_response, "Télécharger")
        self.assertContains(detail_response, "Partager")

    def test_admin_monitoring_shows_camera_controller_management_for_draft_activity(self):
        controller = User.objects.create_user(
            username="camera_draft_agent",
            email="camera_draft_agent@example.com",
            password="CameraPass123!",
            first_name="Brice",
        )
        controller.userprofile.role = UserProfile.CAMERA_CONTROLLER_ROLE
        controller.userprofile.site = self.site
        controller.userprofile.actif = True
        controller.userprofile.save()

        report = CameraOperatorDailyReport.objects.create(
            site=self.site,
            controller=controller,
            date=date(2026, 5, 21),
        )
        CameraObservation.objects.create(
            report=report,
            vehicle_type="MOTO",
            plate_number="CD1234",
            notes="Contrôle en cours.",
        )

        response = self.client.get(
            reverse("admin_site_camera_monitoring", args=[self.site.id]),
            data={"date": "2026-05-21", "month": "2026-05"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestion contrôleurs caméra")
        self.assertContains(response, "Brice")
        self.assertContains(response, "Brouillon en cours")
        self.assertContains(
            response,
            reverse("admin_camera_controller_portal", args=[self.site.id, controller.userprofile.id]),
        )


@override_settings(
    MEDIA_ROOT="/private/tmp/portal_shinecongo_camera_operator_test_media",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@example.com",
    FINAL_REPORT_NOTIFICATION_EMAIL="mbadunkokorigervais@gmail.com",
)
class CameraControllerPortalTests(TestCase):
    def setUp(self):
        self.site = Location.objects.create(
            nom="Site Contrôle Camera",
            adresse="Adresse Controle Camera",
            ville="Kinshasa",
            actif=True,
        )
        self.admin_user = User.objects.create_superuser(
            username="camera_portal_admin",
            email="camera_portal_admin@example.com",
            password="AdminPass123!",
        )
        self.controller = User.objects.create_user(
            username="camera_agent",
            email="camera_agent@example.com",
            password="CameraPass123!",
            first_name="Aline",
        )
        self.controller.userprofile.role = "CONTROLE_CAMERA"
        self.controller.userprofile.site = self.site
        self.controller.userprofile.actif = True
        self.controller.userprofile.save()
        self.camera = Camera.objects.create(
            site=self.site,
            name="Caméra Entrée",
            camera_number=1,
            camera_position="GATE",
            app_name="V380",
            is_active=True,
        )
        self.client.login(username="camera_agent", password="CameraPass123!")

    def test_camera_controller_sees_verification_first_workflow(self):
        dashboard_response = self.client.get(reverse("camera_dashboard"))
        verification_response = self.client.get(reverse("camera_lavage_verification"))

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertContains(dashboard_response, "Lavage verification")
        self.assertContains(dashboard_response, "Signaler un problème")
        self.assertContains(dashboard_response, reverse("camera_signaler_probleme"))
        self.assertContains(dashboard_response, "Travaillez lavage par lavage")
        self.assertNotContains(dashboard_response, "Recette")
        self.assertNotContains(dashboard_response, "Tarif")
        self.assertNotContains(dashboard_response, "FC")
        self.assertEqual(verification_response.status_code, 200)
        self.assertContains(verification_response, "Enregistrer la vérification")
        self.assertContains(verification_response, "Clôture finale de la journée")
        self.assertContains(verification_response, "Plaque")
        self.assertContains(verification_response, "Vérifications enregistrées")
        self.assertNotContains(verification_response, "Choisissez la caméra")
        self.assertNotContains(verification_response, "Preuve horaire")
        self.assertNotContains(verification_response, 'name="camera"', html=False)
        self.assertNotContains(verification_response, "Recette")
        self.assertNotContains(verification_response, "Tarif")
        self.assertNotContains(verification_response, "FC")

    def test_camera_controller_can_record_observation_and_submit_final_report(self):
        response = self.client.post(
            reverse("camera_lavage_verification"),
            data={
                "action": "add_observation",
                "vehicle_type": "CAR",
                "plate_number": " ab1234 ",
                "observed_time": "08:45",
            },
        )

        self.assertRedirects(response, reverse("camera_lavage_verification"), fetch_redirect_response=False)
        report = CameraOperatorDailyReport.objects.get(site=self.site, controller=self.controller, date=timezone.localdate())
        observation = CameraObservation.objects.get(report=report)
        self.assertIsNone(observation.camera)
        self.assertEqual(observation.plate_number, "AB1234")
        self.assertEqual(observation.notes, "")
        self.assertEqual(CameraObservationEvidence.objects.filter(observation=observation).count(), 0)
        self.assertEqual(report.cars_count, 1)
        self.assertEqual(report.total_vehicles, 1)
        self.assertEqual(report.screenshots_count, 0)
        self.assertEqual(report.time_proof_count, 0)
        self.assertEqual(report.expected_revenue, Decimal("15000"))

        preview_response = self.client.post(
            reverse("camera_lavage_verification"),
            data={
                "action": "preview_final_report",
                "notes": "RAS. Caméra entrée stable toute la journée.",
            },
        )

        self.assertEqual(preview_response.status_code, 200)
        report.refresh_from_db()
        self.assertFalse(report.is_submitted)
        self.assertContains(preview_response, "Prévisualisation avant confirmation")
        self.assertContains(preview_response, "Confirmer l'envoi du rapport final")
        self.assertContains(preview_response, "RAS. Caméra entrée stable toute la journée.")
        self.assertEqual(len(mail.outbox), 0)

        submit_response = self.client.post(
            reverse("camera_lavage_verification"),
            data={
                "action": "confirm_final_report",
                "notes": "RAS. Caméra entrée stable toute la journée.",
            },
        )

        self.assertRedirects(submit_response, reverse("camera_lavage_verification"), fetch_redirect_response=False)
        report.refresh_from_db()
        self.assertTrue(report.is_submitted)
        self.assertIsNotNone(report.submitted_at)
        self.assertEqual(report.notes, "RAS. Caméra entrée stable toute la journée.")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Rapport final caméra soumis", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["mbadunkokorigervais@gmail.com"])
        self.assertIn("Contrôleur: Aline", mail.outbox[0].body)
        self.assertIn("Total véhicules: 1", mail.outbox[0].body)
        self.assertIn("Voitures: 1", mail.outbox[0].body)
        self.assertIn("Motos 2 roues: 0", mail.outbox[0].body)
        self.assertIn("Motos 3 roues: 0", mail.outbox[0].body)
        self.assertIn("Montant attendu: 15 000 FC", mail.outbox[0].body)
        self.assertEqual(len(mail.outbox[0].alternatives), 1)
        html_content, mimetype = mail.outbox[0].alternatives[0]
        self.assertEqual(mimetype, "text/html")
        self.assertIn("Rapport final caméra", html_content)
        self.assertIn("Aline", html_content)
        self.assertIn("Montant attendu", html_content)
        self.assertIn("15 000 FC", html_content)

    def test_camera_controller_sees_verification_history(self):
        previous_report = CameraOperatorDailyReport.objects.create(
            site=self.site,
            controller=self.controller,
            date=timezone.localdate() - timedelta(days=1),
            notes="Rapport de la veille.",
            is_submitted=True,
            submitted_at=timezone.now() - timedelta(days=1),
        )
        CameraObservation.objects.create(
            report=previous_report,
            vehicle_type="THREE_WHEELER",
            plate_number="HIST123",
            observed_time=timezone.localtime().time().replace(second=0, microsecond=0),
            notes="Historique de verification.",
        )

        response = self.client.get(reverse("camera_lavage_verification"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Historique des vérifications")
        self.assertContains(response, "HIST123")
        self.assertContains(response, "Historique de verification.")
        self.assertContains(response, "Rapport final soumis")

    def test_camera_controller_report_is_visible_in_admin_monitoring(self):
        report = CameraOperatorDailyReport.objects.create(
            site=self.site,
            controller=self.controller,
            date=timezone.localdate(),
            notes="Rapport final caméra.",
            is_submitted=True,
            submitted_at=timezone.now(),
        )
        observation = CameraObservation.objects.create(
            report=report,
            vehicle_type="MOTO",
            plate_number="AA1022",
            observed_time=timezone.localtime().time().replace(second=0, microsecond=0),
            notes="Moto vue à l'entrée.",
        )
        CameraObservationEvidence.objects.create(
            observation=observation,
            evidence_kind="SCREENSHOT",
            file=SimpleUploadedFile("proof.gif", TEST_GIF_BYTES, content_type="image/gif"),
        )
        report.refresh_from_db()

        admin_client = self.client_class()
        admin_client.login(username="camera_portal_admin", password="AdminPass123!")

        monitoring_response = admin_client.get(reverse("admin_site_camera_monitoring", args=[self.site.id]))
        detail_response = admin_client.get(reverse("admin_camera_operator_report_detail", args=[self.site.id, report.id]))
        download_response = admin_client.get(
            reverse("admin_download_camera_observation_evidence", args=[self.site.id, observation.evidences.first().id])
        )

        self.assertContains(monitoring_response, "Gestion contrôleurs caméra")
        self.assertContains(monitoring_response, "Aline")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(download_response.status_code, 200)
        self.assertIn("attachment;", download_response["Content-Disposition"])
        self.assertIn(observation.evidences.first().filename(), download_response["Content-Disposition"])
        self.assertContains(detail_response, "Moto vue")
        self.assertContains(detail_response, "Captures")
        self.assertContains(detail_response, "Plaque AA1022")
        self.assertContains(detail_response, "Caméra non renseignée")
        self.assertContains(detail_response, "Télécharger")
        self.assertContains(detail_response, "Partager")

    def test_camera_controller_can_report_problem_from_camera_portal(self):
        response = self.client.post(
            reverse("camera_signaler_probleme"),
            data={
                "categorie": "SECURITE",
                "description": "Un véhicule a bloqué l'entrée caméra pendant plusieurs minutes.",
            },
        )

        self.assertRedirects(response, reverse("camera_dashboard"), fetch_redirect_response=False)
        issue = IssueReport.objects.get(site=self.site, employe=self.controller)
        self.assertEqual(issue.categorie, "SECURITE")
        self.assertEqual(issue.statut, "OUVERT")
        self.assertEqual(issue.description, "Un véhicule a bloqué l'entrée caméra pendant plusieurs minutes.")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Problème signalé", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["mbadunkokorigervais@gmail.com"])

        dashboard_response = self.client.get(reverse("camera_dashboard"))
        self.assertContains(dashboard_response, "Problèmes ouverts")
        self.assertContains(dashboard_response, "1 signalement créé aujourd'hui")

    def test_admin_can_correct_controller_report_from_admin_portal(self):
        report = CameraOperatorDailyReport.objects.create(
            site=self.site,
            controller=self.controller,
            date=timezone.localdate(),
        )
        observation = CameraObservation.objects.create(
            report=report,
            vehicle_type="MOTO",
            plate_number=" old99 ",
            notes="Saisie initiale.",
        )

        admin_client = self.client_class()
        admin_client.login(username="camera_portal_admin", password="AdminPass123!")

        response = admin_client.post(
            reverse("admin_camera_controller_portal", args=[self.site.id, self.controller.userprofile.id]),
            data={
                "action": "save_observation",
                "selected_date": timezone.localdate().isoformat(),
                "observation_id": str(observation.id),
                "camera": str(self.camera.id),
                "vehicle_type": "CAR",
                "plate_number": " ab9090 ",
                "observed_time": "09:15",
                "notes": "Correction admin.",
            },
        )

        self.assertEqual(response.status_code, 302)
        observation.refresh_from_db()
        report.refresh_from_db()
        self.assertEqual(observation.camera, self.camera)
        self.assertEqual(observation.vehicle_type, "CAR")
        self.assertEqual(observation.plate_number, "AB9090")
        self.assertEqual(observation.notes, "Correction admin.")
        self.assertEqual(report.cars_count, 1)
        self.assertEqual(report.motos_count, 0)
        self.assertEqual(report.total_vehicles, 1)
        self.assertEqual(report.expected_revenue, Decimal("15000"))

    def test_camera_controller_is_blocked_from_employee_dashboard(self):
        response = self.client.get(reverse("employe_dashboard"), follow=True)

        self.assertRedirects(response, reverse("camera_dashboard"))


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
        self.default_supplier = get_default_water_supplier()
        self.client.login(username="water_admin", password="AdminPass123!")

    def test_admin_can_create_water_purchase(self):
        response = self.client.post(
            reverse("admin_water_purchases"),
            data={
                "site": str(self.site.id),
                "supplier": str(self.default_supplier.id),
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
        self.assertEqual(purchase.supplier, self.default_supplier)
        self.assertEqual(purchase.created_by, self.admin_user)

    def test_admin_can_create_water_supplier_from_water_page(self):
        response = self.client.post(
            f"{reverse('admin_water_purchases')}?month=2026-04",
            data={
                "form_type": "supplier",
                "supplier_setup-name": "Forage Kintambo",
                "supplier_setup-price_per_tank_fc": "27500",
                "supplier_setup-is_active": "on",
                "supplier_setup-notes": "Disponible pour Kintambo et Ngaliema.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            f"{reverse('admin_water_purchases')}?month=2026-04",
            fetch_redirect_response=False,
        )

        supplier = WaterSupplier.objects.get(name="Forage Kintambo")
        self.assertEqual(supplier.price_per_tank_fc, Decimal("27500"))
        self.assertTrue(supplier.is_active)
        self.assertFalse(supplier.is_default)

    def test_water_purchase_page_shows_supplier_management_actions(self):
        purchase = SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 5, 1),
            purchase_date=date(2026, 5, 10),
            amount_fc=Decimal("22000"),
            created_by=self.admin_user,
        )
        response = self.client.get(f"{reverse('admin_water_purchases')}?month=2026-05")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ajouter un fournisseur")
        self.assertContains(response, "Catalogue fournisseurs")
        self.assertContains(response, reverse("admin_move_water_purchase", args=[purchase.id]))
        self.assertContains(response, reverse("admin_mark_water_supplier_paid", args=[self.default_supplier.id]))
        self.assertContains(response, "Payer")
        self.assertContains(
            response,
            reverse("admin_edit_water_supplier", args=[self.default_supplier.id]),
        )

    def test_admin_can_edit_water_supplier_and_make_it_default(self):
        secondary_supplier = WaterSupplier.objects.create(
            name="Forage Binza",
            price_per_tank_fc=Decimal("26000"),
            is_active=True,
        )

        response = self.client.post(
            f"{reverse('admin_edit_water_supplier', args=[secondary_supplier.id])}?month=2026-04",
            data={
                "name": "Forage Binza Premium",
                "price_per_tank_fc": "28500",
                "is_active": "on",
                "is_default": "on",
                "notes": "Nouveau tarif négocié.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            f"{reverse('admin_water_purchases')}?month=2026-04",
            fetch_redirect_response=False,
        )

        secondary_supplier.refresh_from_db()
        self.default_supplier.refresh_from_db()
        self.assertEqual(secondary_supplier.name, "Forage Binza Premium")
        self.assertEqual(secondary_supplier.price_per_tank_fc, Decimal("28500"))
        self.assertTrue(secondary_supplier.is_default)
        self.assertFalse(self.default_supplier.is_default)

    def test_disabling_default_supplier_promotes_another_active_supplier(self):
        replacement_supplier = WaterSupplier.objects.create(
            name="Forage Yolo",
            price_per_tank_fc=Decimal("24500"),
            is_active=True,
        )

        response = self.client.post(
            f"{reverse('admin_edit_water_supplier', args=[self.default_supplier.id])}?month=2026-04",
            data={
                "name": self.default_supplier.name,
                "price_per_tank_fc": "22000",
                "notes": "Ancien fournisseur principal.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            f"{reverse('admin_water_purchases')}?month=2026-04",
            fetch_redirect_response=False,
        )

        self.default_supplier.refresh_from_db()
        replacement_supplier.refresh_from_db()
        self.assertFalse(self.default_supplier.is_active)
        self.assertFalse(self.default_supplier.is_default)
        self.assertTrue(replacement_supplier.is_default)

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
        self.assertContains(response, "Honosha")
        self.assertContains(response, reverse("admin_water_purchases"))

    def test_water_purchase_page_uses_default_supplier_rate(self):
        response = self.client.get(reverse("admin_water_purchases"), data={"month": "2026-05"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["default_amount"], Decimal("22000"))
        self.assertEqual(response.context["form"].fields["amount_fc"].initial, Decimal("22000"))
        self.assertContains(response, "Honosha's Forage")
        self.assertContains(response, "22 000 FC")
        self.assertContains(response, "Répartition par fournisseur")

    def test_water_purchase_page_keeps_default_supplier_rate_for_other_months(self):
        response = self.client.get(reverse("admin_water_purchases"), data={"month": "2026-04"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["default_amount"], Decimal("22000"))
        self.assertEqual(response.context["form"].fields["amount_fc"].initial, Decimal("22000"))
        self.assertContains(response, "Honosha's Forage")
        self.assertContains(response, "22 000 FC")

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

    def test_water_purchase_view_places_out_of_month_purchase_in_general_bucket(self):
        SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 5, 1),
            purchase_date=date(2026, 6, 2),
            amount_fc=Decimal("22000"),
            notes="Achat deja regle pour mai",
            created_by=self.admin_user,
        )

        response = self.client.get(reverse("admin_water_purchases"), data={"month": "2026-05"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "General du mois")
        self.assertEqual(response.context["general_breakdown"]["count"], 1)
        self.assertEqual(response.context["general_breakdown"]["total"], Decimal("22000"))

    def test_admin_can_migrate_water_purchase_to_general_month(self):
        purchase = SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 5, 1),
            purchase_date=date(2026, 5, 29),
            amount_fc=Decimal("22000"),
            notes="Dernier achat de mai",
            created_by=self.admin_user,
        )

        response = self.client.post(
            f"{reverse('admin_move_water_purchase', args=[purchase.id])}?month=2026-05",
            data={
                "billing_month": "2026-06",
                "assignment_scope": "GENERAL",
                "reporting_week_date": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            f"{reverse('admin_water_purchases')}?month=2026-06",
            fetch_redirect_response=False,
        )

        purchase.refresh_from_db()
        self.assertEqual(purchase.billing_month, date(2026, 6, 1))
        self.assertEqual(purchase.purchase_date, date(2026, 5, 29))
        self.assertIsNone(purchase.reporting_week_date)

        june_response = self.client.get(reverse("admin_water_purchases"), data={"month": "2026-06"})
        self.assertContains(june_response, "General du mois")
        self.assertEqual(june_response.context["general_breakdown"]["count"], 1)

    def test_admin_can_migrate_water_purchase_to_specific_week(self):
        purchase = SiteWaterPurchase.objects.create(
            site=self.site,
            billing_month=date(2026, 5, 1),
            purchase_date=date(2026, 5, 29),
            amount_fc=Decimal("22000"),
            notes="Dernier achat de mai",
            created_by=self.admin_user,
        )

        response = self.client.post(
            f"{reverse('admin_move_water_purchase', args=[purchase.id])}?month=2026-05",
            data={
                "billing_month": "2026-06",
                "assignment_scope": "WEEK",
                "reporting_week_date": "2026-06-10",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            f"{reverse('admin_water_purchases')}?month=2026-06",
            fetch_redirect_response=False,
        )

        purchase.refresh_from_db()
        self.assertEqual(purchase.billing_month, date(2026, 6, 1))
        self.assertEqual(purchase.purchase_date, date(2026, 5, 29))
        self.assertEqual(purchase.reporting_week_date, date(2026, 6, 10))

        june_response = self.client.get(reverse("admin_water_purchases"), data={"month": "2026-06"})
        self.assertEqual(june_response.context["general_breakdown"]["count"], 0)
        self.assertContains(june_response, "Semaine du 08/06 au 14/06")
        self.assertTrue(
            any(
                item["week_start"] == date(2026, 6, 8)
                and item["count"] == 1
                and item["total"] == Decimal("22000")
                for item in june_response.context["weekly_breakdown"]
            )
        )

    def test_admin_can_mark_supplier_paid_and_reduce_month_unpaid_total(self):
        secondary_supplier = WaterSupplier.objects.create(
            name="Innocent Mushawhili",
            price_per_tank_fc=Decimal("32000"),
            is_active=True,
        )
        paid_purchase = SiteWaterPurchase.objects.create(
            site=self.site,
            supplier=self.default_supplier,
            billing_month=date(2026, 6, 1),
            purchase_date=date(2026, 6, 2),
            amount_fc=Decimal("22000"),
            created_by=self.admin_user,
        )
        unpaid_purchase = SiteWaterPurchase.objects.create(
            site=self.site,
            supplier=secondary_supplier,
            billing_month=date(2026, 6, 1),
            purchase_date=date(2026, 6, 3),
            amount_fc=Decimal("64000"),
            created_by=self.admin_user,
        )

        response = self.client.post(
            f"{reverse('admin_mark_water_supplier_paid', args=[self.default_supplier.id])}?month=2026-06"
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            f"{reverse('admin_water_purchases')}?month=2026-06",
            fetch_redirect_response=False,
        )

        paid_purchase.refresh_from_db()
        unpaid_purchase.refresh_from_db()
        self.assertIsNotNone(paid_purchase.paid_at)
        self.assertEqual(paid_purchase.paid_by, self.admin_user)
        self.assertIsNone(unpaid_purchase.paid_at)

        june_response = self.client.get(reverse("admin_water_purchases"), data={"month": "2026-06"})
        self.assertEqual(june_response.context["month_total"], Decimal("86000"))
        self.assertEqual(june_response.context["month_paid_total"], Decimal("22000"))
        self.assertEqual(june_response.context["month_unpaid_total"], Decimal("64000"))
        self.assertContains(june_response, "Déjà payé")
        self.assertContains(june_response, "Reste à payer")

        default_supplier_row = next(
            item for item in june_response.context["supplier_breakdown"]
            if item["supplier_id"] == self.default_supplier.id
        )
        other_supplier_row = next(
            item for item in june_response.context["supplier_breakdown"]
            if item["supplier_id"] == secondary_supplier.id
        )
        self.assertTrue(default_supplier_row["is_fully_paid"])
        self.assertEqual(default_supplier_row["unpaid_total"], Decimal("0"))
        self.assertEqual(other_supplier_row["unpaid_total"], Decimal("64000"))


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

    def test_history_comparison_ranks_weeks_within_each_month_by_cash_flow(self):
        CarWash.objects.create(
            employe=self.admin_user,
            site=self.site,
            date=date(2026, 4, 3),
            type_service="COMPLET",
            montant=Decimal("5000"),
        )
        CarWash.objects.create(
            employe=self.admin_user,
            site=self.site,
            date=date(2026, 4, 28),
            type_service="COMPLET",
            montant=Decimal("15000"),
        )

        response = self.client.get(
            reverse("admin_site_history_comparison", args=[self.site.id]),
            data={"scope": "month", "date": "2026-04-21"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Classement hebdomadaire par mois")

        april_ranking = next(
            item
            for item in response.context["monthly_rankings_period"]["weekly_cash_rankings"]
            if item["month_label"] == "Avril 2026"
        )
        self.assertEqual(
            [week["cash_flow"] for week in april_ranking["weeks"][:3]],
            [Decimal("15000"), Decimal("10000"), Decimal("5000")],
        )
        self.assertEqual(april_ranking["weeks"][0]["rank"], 1)
        self.assertTrue(april_ranking["weeks"][0]["is_best"])

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
