from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User

from comptes.forms import ApprovalAuthenticationForm
from sites.models import Location


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
        self.assertContains(response, "Demandes de comptes en attente")
        self.assertContains(response, "pending_candidate")
        self.assertContains(response, "Site Pending")
        self.assertContains(response, "Adresse Pending")

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
