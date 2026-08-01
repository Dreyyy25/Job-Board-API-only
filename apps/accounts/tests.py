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


class CookieAuthTests(APITestCase):
    """Refresh tokens move to an httpOnly cookie; body keeps only access."""

    def _assert_refresh_cookie_set(self, response):
        cookie_conf = django_settings.AUTH_REFRESH_COOKIE
        name = cookie_conf["NAME"]
        self.assertIn(name, response.cookies,
                      f"Expected {name!r} cookie in response")
        morsel = response.cookies[name]
        self.assertTrue(morsel["httponly"])
        self.assertEqual(morsel["samesite"], "Lax")
        self.assertEqual(morsel["path"], "/api/v1/accounts/")
        self.assertEqual(morsel["max-age"], 604800)  # 7 days
        self.assertTrue(morsel.value, "Refresh token cookie value is empty")

        self.assertIn("access", response.data["tokens"])
        self.assertNotIn("refresh", response.data["tokens"])

    def test_register_sets_refresh_cookie_and_omits_it_from_body(self):
        r = self.client.post("/api/v1/accounts/register/", {
            "email": "cookie-register@example.com",
            "password": "Str0ng-Password!",
            "user_type": "job_seeker",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self._assert_refresh_cookie_set(r)
        self.assertEqual(r.data["user"], {
            "id": r.data["user"]["id"],
            "email": "cookie-register@example.com",
            "user_type": "job_seeker",
        })

    def test_login_sets_refresh_cookie_and_omits_it_from_body(self):
        UserAccount.objects.create_user(
            email="cookie-login@example.com",
            password="Str0ng-Password!",
            user_type="job_seeker",
        )
        r = self.client.post("/api/v1/accounts/login/", {
            "email": "cookie-login@example.com",
            "password": "Str0ng-Password!",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self._assert_refresh_cookie_set(r)
        self.assertEqual(r.data["user"], {
            "id": r.data["user"]["id"],
            "email": "cookie-login@example.com",
            "user_type": "job_seeker",
        })


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


from unittest.mock import patch
from apps.companies.models import Company
from apps.seekers.models import SeekerProfile


class SignalCreatedProfileTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_registering_seeker_creates_profile(self):
        r = self.client.post("/api/v1/accounts/register/", {
            "email": "sig-seeker@example.com",
            "password": "Str0ng-Password!",
            "user_type": "job_seeker",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        user = UserAccount.objects.get(email="sig-seeker@example.com")
        self.assertTrue(SeekerProfile.objects.filter(user_account=user).exists())

    def test_registering_company_creates_company_row(self):
        r = self.client.post("/api/v1/accounts/register/", {
            "email": "sig-co@example.com",
            "password": "Str0ng-Password!",
            "user_type": "company",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        user = UserAccount.objects.get(email="sig-co@example.com")
        co = Company.objects.get(user_account=user)
        self.assertEqual(co.business_stream.business_stream_name, "Uncategorized")

    def test_signal_creates_company_on_create_superuser(self):
        user = UserAccount.objects.create_superuser(
            email="su@example.com", password="Str0ng-Password!",
        )
        self.assertTrue(Company.objects.filter(user_account=user).exists())

    def test_signal_creates_seeker_profile_on_create_user(self):
        user = UserAccount.objects.create_user(
            email="cu-seeker@example.com", password="Str0ng-Password!",
            user_type="job_seeker",
        )
        self.assertTrue(SeekerProfile.objects.filter(user_account=user).exists())

    def test_signal_idempotent_on_resave(self):
        user = UserAccount.objects.create_user(
            email="idem@example.com", password="Str0ng-Password!",
            user_type="job_seeker",
        )
        user.save()  # re-save
        self.assertEqual(
            SeekerProfile.objects.filter(user_account=user).count(), 1,
        )

    def test_register_rollback_on_signal_failure(self):
        email = "rollback-register@example.com"
        with patch(
            "apps.seekers.models.SeekerProfile.objects.get_or_create",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/v1/accounts/register/", {
                    "email": email,
                    "password": "Str0ng-Password!",
                    "user_type": "job_seeker",
                }, format="json")
        self.assertEqual(UserAccount.objects.filter(email=email).count(), 0)

    def test_create_user_rollback_on_signal_failure(self):
        email = "rollback-cu@example.com"
        with patch(
            "apps.seekers.models.SeekerProfile.objects.get_or_create",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                UserAccount.objects.create_user(
                    email=email, password="Str0ng-Password!",
                    user_type="job_seeker",
                )
        self.assertEqual(UserAccount.objects.filter(email=email).count(), 0)

    def test_register_response_includes_seeker_profile(self):
        r = self.client.post("/api/v1/accounts/register/", {
            "email": "resp-seeker@example.com",
            "password": "Str0ng-Password!",
            "user_type": "job_seeker",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertIn("profile", r.data)
        self.assertIsNotNone(r.data["profile"])
        # SeekerProfile serializer includes first_name/last_name
        self.assertIn("first_name", r.data["profile"])

    def test_register_response_includes_company_profile(self):
        r = self.client.post("/api/v1/accounts/register/", {
            "email": "resp-co@example.com",
            "password": "Str0ng-Password!",
            "user_type": "company",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertIn("profile", r.data)
        self.assertIn("company_name", r.data["profile"])


from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.accounts import services


class Argon2HasherTests(APITestCase):
    """Argon2 is configured in base.py; test.py overrides to MD5 for speed.

    We use override_settings here to exercise the real hasher.
    """

    @override_settings(PASSWORD_HASHERS=[
        'django.contrib.auth.hashers.Argon2PasswordHasher',
        'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    ])
    def test_new_user_password_stored_with_argon2(self):
        user = UserAccount.objects.create_user(
            email='argon@example.com',
            password='Str0ng-Password!',
            user_type='job_seeker',
        )
        self.assertTrue(
            user.password.startswith('argon2'),
            f"Expected argon2 hash, got {user.password[:10]}",
        )


class AccountsServiceTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_register_user_returns_user_and_tokens(self):
        user, tokens = services.register_user(
            email="svc-seeker@example.com",
            password="Str0ng-Password!",
            user_type="job_seeker",
        )
        self.assertEqual(user.email, "svc-seeker@example.com")
        self.assertIn("access", tokens)
        self.assertIn("refresh", tokens)

    def test_register_user_rejects_weak_password(self):
        with self.assertRaises(DjangoValidationError):
            services.register_user(
                email="weak@example.com",
                password="abc",
                user_type="job_seeker",
            )

    def test_register_user_prefetches_profile(self):
        user, _ = services.register_user(
            email="prefetch@example.com",
            password="Str0ng-Password!",
            user_type="job_seeker",
        )
        with CaptureQueriesContext(connection) as ctx:
            _ = user.seeker_profile
        self.assertEqual(len(ctx), 0)

    def test_login_user_happy_path(self):
        UserAccount.objects.create_user(
            email="login-svc@example.com",
            password="Str0ng-Password!",
            user_type="job_seeker",
        )
        user, tokens = services.login_user(
            "login-svc@example.com", "Str0ng-Password!",
        )
        self.assertEqual(user.email, "login-svc@example.com")
        self.assertIn("access", tokens)

    def test_login_user_unknown_email_raises(self):
        with self.assertRaises(services.InvalidCredentialsError):
            services.login_user("nobody@example.com", "x")

    def test_login_user_bad_password_raises(self):
        UserAccount.objects.create_user(
            email="bad-pass@example.com",
            password="Str0ng-Password!",
            user_type="job_seeker",
        )
        with self.assertRaises(services.InvalidCredentialsError):
            services.login_user("bad-pass@example.com", "wrong")

    def test_logout_user_invalid_token_raises(self):
        with self.assertRaises(services.InvalidTokenError):
            services.logout_user("not-a-real-token")

    def test_logout_user_missing_token_raises(self):
        with self.assertRaises(services.InvalidTokenError):
            services.logout_user(None)


class FailedLoginLoggingTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_failed_login_logs_security_warning_with_hash_not_plaintext(self):
        plaintext_email = "ghost@example.com"
        with self.assertLogs('django.security', level='WARNING') as cm:
            r = self.client.post('/api/v1/accounts/login/', {
                'email': plaintext_email,
                'password': 'wrong',
            }, format='json')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
        log_output = '\n'.join(cm.output)
        self.assertIn('email_hash=', log_output)
        # Plaintext email must NOT appear in the log line.
        self.assertNotIn(plaintext_email, log_output)

    def test_failed_login_on_existing_user_also_logs(self):
        UserAccount.objects.create_user(
            email='fl-existing@example.com',
            password='Str0ng-Password!',
            user_type='job_seeker',
        )
        with self.assertLogs('django.security', level='WARNING') as cm:
            r = self.client.post('/api/v1/accounts/login/', {
                'email': 'fl-existing@example.com',
                'password': 'wrong',
            }, format='json')
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('email_hash=', '\n'.join(cm.output))


class RegisterQueryCountTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_register_endpoint_prefetches_profile_reasonably(self):
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.post("/api/v1/accounts/register/", {
                "email": "qc-reg@example.com",
                "password": "Str0ng-Password!",
                "user_type": "job_seeker",
            }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertLessEqual(
            len(ctx), 20,
            f"Register query count {len(ctx)} unexpectedly high",
        )


class OpenAPISchemaTests(APITestCase):
    """drf-spectacular: schema is reachable and lists our endpoints."""

    def test_schema_endpoint_returns_200_and_yaml(self):
        r = self.client.get('/api/schema/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        # Default content type is application/vnd.oai.openapi (YAML).
        self.assertIn('openapi', r.content[:200].decode('utf-8', errors='replace'))

    def test_swagger_ui_loads(self):
        r = self.client.get('/api/docs/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_schema_includes_key_paths(self):
        r = self.client.get('/api/schema/?format=json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        paths = r.json().get('paths', {})
        for expected in (
            '/api/v1/accounts/register/',
            '/api/v1/accounts/login/',
            '/api/v1/jobs/job-posts/',
            '/api/v1/jobs/apply/',
            '/api/v1/companies/profile/',
            '/api/v1/seekers/profiles/',
        ):
            self.assertIn(expected, paths, f'Missing path: {expected}')

    def test_schema_advertises_jwt_bearer_auth(self):
        r = self.client.get('/api/schema/?format=json')
        components = r.json().get('components', {})
        security_schemes = components.get('securitySchemes', {})
        self.assertIn('jwtAuth', security_schemes)
        self.assertEqual(security_schemes['jwtAuth']['scheme'], 'bearer')
        self.assertEqual(security_schemes['jwtAuth']['bearerFormat'], 'JWT')


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

    def test_samesite_lax_configured(self):
        self.assertEqual(django_settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(django_settings.CSRF_COOKIE_SAMESITE, 'Lax')
        self.assertTrue(django_settings.SESSION_COOKIE_HTTPONLY)
        self.assertFalse(django_settings.CSRF_COOKIE_HTTPONLY)
