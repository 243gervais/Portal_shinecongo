from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.cache import caches
from django.http import HttpResponse
from django.test import SimpleTestCase, override_settings

from comptes.image_utils import get_thumbnail_url, remember_thumbnail
from shinecongo.middleware import RequestTimingMiddleware


@override_settings(CACHES={
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    'image_metadata': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
})
class ThumbnailRenderingTests(SimpleTestCase):
    def setUp(self):
        caches['image_metadata'].clear()
        self.storage = Mock(bucket_name='photos', location='media')
        self.storage.url.side_effect = lambda name: f'/media/{name}'
        self.photo = SimpleNamespace(name='proof.jpg', url='/media/proof.jpg', storage=self.storage)

    def test_cold_cache_uses_original_without_any_remote_storage_io(self):
        self.assertEqual(get_thumbnail_url(self.photo), '/media/proof.jpg')
        self.storage.exists.assert_not_called()
        self.storage.open.assert_not_called()
        self.storage.save.assert_not_called()

    def test_prepared_thumbnail_is_reused_without_remote_storage_io(self):
        remember_thumbnail(self.photo, 'proof__thumb.webp')
        self.assertEqual(get_thumbnail_url(self.photo), '/media/proof__thumb.webp')
        self.storage.exists.assert_not_called()
        self.storage.open.assert_not_called()

    def test_clearing_metadata_falls_back_safely(self):
        remember_thumbnail(self.photo, 'proof__thumb.webp')
        caches['image_metadata'].clear()
        self.assertEqual(get_thumbnail_url(self.photo), '/media/proof.jpg')
        self.storage.exists.assert_not_called()


class RequestTimingTests(SimpleTestCase):
    @patch('shinecongo.middleware.perf_counter', side_effect=[10, 13])
    def test_slow_requests_are_logged_without_private_query_or_body(self, _clock):
        request = SimpleNamespace(path='/admin-dashboard/', method='GET', resolver_match=SimpleNamespace(view_name='admin_dashboard'))
        middleware = RequestTimingMiddleware(lambda request: HttpResponse('ok'))
        with self.assertLogs('shinecongo.performance', level='WARNING') as logs:
            response = middleware(request)
        self.assertEqual(response['Server-Timing'], 'app;dur=3000.0')
        self.assertIn('route=admin_dashboard', logs.output[0])
