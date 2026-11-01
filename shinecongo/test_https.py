from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from shinecongo.middleware import CanonicalPortalHostMiddleware


@override_settings(
    ALLOWED_HOSTS=['portal.shinecongo.org', '8-229-62-95.nip.io', 'testserver'],
    PORTAL_CANONICAL_HOST='portal.shinecongo.org',
)
class CanonicalHostTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = CanonicalPortalHostMiddleware(lambda request: HttpResponse('ok'))

    def test_legacy_navigation_preserves_path_and_filters(self):
        request = self.factory.get('/login/?next=%2Fmanager%2F', HTTP_HOST='8-229-62-95.nip.io')
        response = self.middleware(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'https://portal.shinecongo.org/login/?next=%2Fmanager%2F')
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_canonical_host_does_not_loop(self):
        self.assertEqual(self.middleware(self.factory.get('/', HTTP_HOST='portal.shinecongo.org')).status_code, 200)

    def test_post_is_never_replayed_on_another_host(self):
        self.assertEqual(self.middleware(self.factory.post('/login/', HTTP_HOST='8-229-62-95.nip.io')).status_code, 200)

    def test_development_host_is_not_redirected(self):
        self.assertEqual(self.middleware(self.factory.get('/')).status_code, 200)

    @override_settings(PORTAL_CANONICAL_HOST='')
    def test_unconfigured_install_is_unchanged(self):
        self.assertEqual(self.middleware(self.factory.get('/', HTTP_HOST='8-229-62-95.nip.io')).status_code, 200)

    def test_forwarded_https_is_used_for_generated_links(self):
        request = self.factory.get('/manager/', HTTP_HOST='portal.shinecongo.org', HTTP_X_FORWARDED_PROTO='https')
        self.assertTrue(request.is_secure())
        self.assertEqual(request.build_absolute_uri(), 'https://portal.shinecongo.org/manager/')
