from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import UserAccount


class PasswordPolicyTests(APITestCase):
    def test_register_rejects_short_password(self):
        payload = {
            "email": "short@example.com",
            "password": "abc123",
            "user_type": "job_seeker",
        }
        r = self.client.post("/api/v1/accounts/register/", payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", r.data)

    def test_register_rejects_common_password(self):
        payload = {
            "email": "common@example.com",
            "password": "password123",
            "user_type": "job_seeker",
        }
        r = self.client.post("/api/v1/accounts/register/", payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", r.data)


class RegisterHardeningTests(APITestCase):
    def _payload(self, **overrides):
        base = {
            "email": "newuser@example.com",
            "password": "Str0ng-Password!",
            "user_type": "job_seeker",
        }
        base.update(overrides)
        return base

    def test_register_ignores_is_staff_flag(self):
        r = self.client.post("/api/v1/accounts/register/",
                             self._payload(is_staff=True, is_superuser=True),
                             format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        user = UserAccount.objects.get(email="newuser@example.com")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_register_requires_user_type(self):
        payload = self._payload()
        payload.pop("user_type")
        r = self.client.post("/api/v1/accounts/register/", payload, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class MePatchTests(APITestCase):
    def setUp(self):
        self.user = UserAccount.objects.create_user(
            email="seeker@example.com",
            password="Str0ng-Password!",
            user_type="job_seeker",
        )
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_me_patch_rejects_is_staff_escalation(self):
        r = self.client.patch("/api/v1/accounts/me/",
                              {"is_staff": True, "is_superuser": True},
                              format="json")
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)

    def test_me_patch_rejects_user_type_change(self):
        r = self.client.patch("/api/v1/accounts/me/",
                              {"user_type": "company"},
                              format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertEqual(self.user.user_type, "job_seeker")

    def test_users_cannot_see_other_users(self):
        other = UserAccount.objects.create_user(
            email="other@example.com",
            password="Str0ng-Password!",
            user_type="company",
        )
        r = self.client.get(f"/api/v1/accounts/users/{other.id}/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class LogoutTests(APITestCase):
    def setUp(self):
        self.user = UserAccount.objects.create_user(
            email="logout@example.com",
            password="Str0ng-Password!",
            user_type="job_seeker",
        )
        self.refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.refresh.access_token}")

    def test_logout_blacklists_refresh_token(self):
        r = self.client.post("/api/v1/accounts/logout/",
                             {"refresh": str(self.refresh)}, format="json")
        self.assertEqual(r.status_code, status.HTTP_205_RESET_CONTENT)
        self.client.credentials()  # drop auth header
        r2 = self.client.post("/api/v1/accounts/token/refresh/",
                              {"refresh": str(self.refresh)}, format="json")
        self.assertEqual(r2.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_missing_refresh_returns_400(self):
        r = self.client.post("/api/v1/accounts/logout/", {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


from django.core.cache import cache


class ThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_register_throttles_after_limit(self):
        url = "/api/v1/accounts/register/"
        for i in range(5):
            r = self.client.post(url, {
                "email": f"thr{i}@example.com",
                "password": "Str0ng-Password!",
                "user_type": "job_seeker",
            }, format="json")
            self.assertIn(r.status_code, (status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST))
        r6 = self.client.post(url, {
            "email": "thr6@example.com",
            "password": "Str0ng-Password!",
            "user_type": "job_seeker",
        }, format="json")
        self.assertEqual(r6.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


from django.test import override_settings


@override_settings(
    CORS_ALLOWED_ORIGINS=["http://localhost:3000"],
    CORS_ALLOW_ALL_ORIGINS=False,
)
class CorsTests(APITestCase):
    def test_cors_preflight_from_allowed_origin(self):
        r = self.client.options(
            "/api/v1/accounts/login/",
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"),
                         "http://localhost:3000")

    def test_cors_preflight_from_disallowed_origin(self):
        r = self.client.options(
            "/api/v1/accounts/login/",
            HTTP_ORIGIN="http://evil.example.com",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )
        self.assertNotIn("Access-Control-Allow-Origin", r.headers)


class SecurityHeaderTests(APITestCase):
    def test_x_frame_options_deny(self):
        r = self.client.get("/api/v1/accounts/register/")
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")

    def test_content_type_nosniff(self):
        r = self.client.get("/api/v1/accounts/register/")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")

    def test_referrer_policy_same_origin(self):
        r = self.client.get("/api/v1/accounts/register/")
        self.assertEqual(r.headers.get("Referrer-Policy"), "same-origin")

    @override_settings(SECURE_HSTS_SECONDS=3600, SECURE_SSL_REDIRECT=False)
    def test_hsts_header_present_when_configured(self):
        # SecurityMiddleware only sets HSTS on HTTPS requests;
        # APIClient can simulate that via HTTPS=on / wsgi.url_scheme.
        r = self.client.get("/api/v1/accounts/register/", secure=True)
        self.assertIn("max-age=3600", r.headers.get("Strict-Transport-Security", ""))


from django.conf import settings as django_settings


class SettingsModuleTests(APITestCase):
    """Verify we're running under the test settings module."""

    def test_debug_is_false(self):
        self.assertFalse(django_settings.DEBUG)

    def test_password_hasher_is_md5(self):
        self.assertTrue(
            django_settings.PASSWORD_HASHERS[0].endswith('MD5PasswordHasher'),
            f"Expected MD5 hasher, got {django_settings.PASSWORD_HASHERS[0]}",
        )

    def test_ssl_redirect_off_in_tests(self):
        self.assertFalse(django_settings.SECURE_SSL_REDIRECT)

    def test_testserver_in_allowed_hosts(self):
        self.assertIn('testserver', django_settings.ALLOWED_HOSTS)
