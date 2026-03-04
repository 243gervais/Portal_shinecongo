from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from comptes.models import UserProfile
from lavages.models import CarWash, CarWashPhoto
from sites.models import Location


class AjouterLavageDuplicateProtectionTests(TestCase):
    def setUp(self):
        self.site = Location.objects.create(
            nom="Ngolomingo",
            adresse="Kinshasa",
            actif=True,
        )
        self.user = User.objects.create_user(
            username="employe_test",
            password="StrongPass123!",
        )
        profile = self.user.userprofile
        profile.role = "EMPLOYE"
        profile.site = self.site
        profile.actif = True
        profile.save()

        self.client.login(username="employe_test", password="StrongPass123!")

    def _post_lavage(self, montant="15000.00"):
        image = SimpleUploadedFile(
            "photo.jpg",
            b"fake-image-content",
            content_type="image/jpeg",
        )
        return self.client.post(
            reverse("ajouter_lavage"),
            data={
                "type_service": "COMPLET",
                "plaque_mode": "manual",
                "plaque": "ABCD123",
                "montant": montant,
                "notes": "test lavage",
                "photos": [image],
            },
        )

    def test_duplicate_submission_is_blocked(self):
        first_response = self._post_lavage()
        second_response = self._post_lavage()

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(CarWash.objects.count(), 1)
        self.assertEqual(CarWashPhoto.objects.count(), 1)

    def test_distinct_submission_is_allowed(self):
        self._post_lavage(montant="15000.00")
        self._post_lavage(montant="20000.00")

        self.assertEqual(CarWash.objects.count(), 2)
