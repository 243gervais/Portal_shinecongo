from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User

from comptes.forms import ApprovalAuthenticationForm


class AccountApprovalFlowTests(TestCase):
    def test_registration_creates_inactive_account(self):
        response = self.client.post(
            reverse("register"),
            data={
                "username": "pending_user",
                "password1": "testpass1234",
                "password2": "testpass1234",
                "site_nom": "Site Test",
                "site_adresse": "Adresse Test",
                "telephone": "123456789",
            },
        )

        self.assertRedirects(response, reverse("login"))
        user = User.objects.get(username="pending_user")
        self.assertFalse(user.is_active)
        self.assertFalse(user.userprofile.actif)

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
