from io import BytesIO
from tempfile import TemporaryDirectory
from uuid import uuid4
from unittest.mock import patch

from PIL import Image
from botocore.exceptions import EndpointConnectionError
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from lavages.models import CarWash, CarWashPhoto
from pointage.models import ShiftDay, ManagerEquipmentPhoto
from sites.models import Location, ManagerManualMachine


def photo(name='phone.jpg', content_type='image/jpeg'):
    stream = BytesIO()
    Image.new('RGB', (80, 60), 'navy').save(stream, 'JPEG')
    return SimpleUploadedFile(name, stream.getvalue(), content_type=content_type)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ManagerUploadTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        settings = override_settings(MEDIA_ROOT=self.media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.site = Location.objects.create(nom='Upload test')
        self.manager = User.objects.create_user('upload-manager')
        profile = self.manager.userprofile
        profile.role = 'MANAGER'
        profile.site = self.site
        profile.save()
        self.client.force_login(self.manager)
        ManagerManualMachine.objects.all().delete()
        self.wash_url = reverse('portal_api_manager_lavages')
        self.report_url = reverse('portal_api_manager_report')

    def wash(self, token=None, **extra):
        return self.client.post(self.wash_url, {'submission_id': str(token or uuid4()),
            'type_service': 'COMPLET', 'photos': photo(), **extra})

    def test_different_cars_with_blank_plates_are_not_false_duplicates(self):
        self.assertEqual(self.wash().status_code, 201)
        self.assertEqual(self.wash().status_code, 201)
        self.assertEqual(CarWash.objects.filter(is_system_generated=False).count(), 2)

    def test_retry_returns_saved_wash_even_without_reuploading(self):
        token = uuid4()
        first = self.wash(token)
        retry = self.client.post(self.wash_url, {'submission_id': str(token)})
        self.assertEqual(first.status_code, 201)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(first.json()['lavage']['id'], retry.json()['lavage']['id'])
        self.assertEqual(CarWashPhoto.objects.count(), 1)

    def test_another_manager_cannot_replay_someone_elses_submission(self):
        token = uuid4()
        self.wash(token)
        other = User.objects.create_user('other-manager')
        profile = other.userprofile
        profile.role, profile.site = 'MANAGER', self.site
        profile.save()
        self.client.force_login(other)
        self.assertEqual(self.wash(token).status_code, 409)

    def test_corrupt_photo_batch_creates_no_partial_wash(self):
        invalid = SimpleUploadedFile('fake.jpg', b'not an image', content_type='image/jpeg')
        result = self.client.post(self.wash_url, {'type_service': 'COMPLET', 'photos': [photo(), invalid]})
        self.assertEqual(result.status_code, 400)
        self.assertFalse(CarWash.objects.exists())
        self.assertFalse(CarWashPhoto.objects.exists())

    def test_oversized_photo_and_too_many_files_are_rejected_before_save(self):
        huge = SimpleUploadedFile('large.jpg', b'x' * (10 * 1024 * 1024 + 1), content_type='image/jpeg')
        self.assertEqual(self.wash(photos=huge).status_code, 400)
        self.assertEqual(self.wash(photos=[photo(f'{i}.jpg') for i in range(21)]).status_code, 400)
        self.assertFalse(CarWash.objects.exists())

    def test_real_image_without_image_mime_is_accepted(self):
        self.assertEqual(self.wash(photos=photo(content_type='application/octet-stream')).status_code, 201)

    def test_storage_failure_rolls_back_and_same_token_can_be_retried(self):
        token = uuid4()
        with patch('lavages.models.CarWashPhoto.save', side_effect=EndpointConnectionError(endpoint_url='https://storage.invalid')):
            self.assertEqual(self.wash(token).status_code, 503)
        self.assertFalse(CarWash.objects.exists())
        self.assertEqual(self.wash(token).status_code, 201)

    def test_report_image_validation_does_not_confirm_failed_report(self):
        machine = ManagerManualMachine.objects.create(name='Aspirateur')
        invalid = SimpleUploadedFile('bad.jpg', b'invalid', content_type='image/jpeg')
        result = self.client.post(self.report_url, {'equipment_photo_machine_id': str(machine.pk), 'equipment_photo': invalid})
        self.assertEqual(result.status_code, 400)
        self.assertFalse(ShiftDay.objects.filter(daily_report_confirmed=True).exists())

    def test_report_storage_failure_rolls_back_confirmation(self):
        machine = ManagerManualMachine.objects.create(name='Aspirateur')
        with patch('pointage.models.ManagerEquipmentPhoto.save', side_effect=EndpointConnectionError(endpoint_url='https://storage.invalid')):
            result = self.client.post(self.report_url, {'equipment_photo_machine_id': str(machine.pk), 'equipment_photo': photo()})
        self.assertEqual(result.status_code, 503)
        self.assertFalse(ShiftDay.objects.filter(daily_report_confirmed=True).exists())

    def test_report_accepts_real_equipment_photo_with_generic_mime(self):
        machine = ManagerManualMachine.objects.create(name='Aspirateur')
        result = self.client.post(self.report_url, {'equipment_photo_machine_id': str(machine.pk), 'equipment_photo': photo(content_type='application/octet-stream')})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(ShiftDay.objects.get(employe=self.manager, date=timezone.localdate()).daily_report_confirmed)
        self.assertEqual(ManagerEquipmentPhoto.objects.count(), 1)

    def test_report_rejects_nonfinite_and_out_of_range_amounts(self):
        for value in ('Infinity', 'NaN', '99999999999999999999999'):
            with self.subTest(amount=value):
                self.assertEqual(self.client.post(self.report_url, {'total_amount_reported_fc': value}).status_code, 400)

    def test_employee_cannot_use_manager_upload_endpoints(self):
        employee = User.objects.create_user('upload-employee')
        self.client.force_login(employee)
        self.assertEqual(self.wash().status_code, 403)
        self.assertEqual(self.client.post(self.report_url, {}).status_code, 403)
