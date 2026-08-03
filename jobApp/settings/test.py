"""Test settings — fast password hashing, loose host list, no SSL redirect."""
from .base import *  # noqa: F401,F403
from .base import REST_FRAMEWORK as _BASE_RF

DEBUG = False

# Django's test client sends Host: testserver.
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']

# Dramatic speedup for UserAccount.create_user(...) in setUp blocks.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Tests talk HTTP.
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
# base defaults this to True (secure-by-default); test.py imports from base
# only (not development), so the HTTP-friendly value must be restated here.
AUTH_REFRESH_COOKIE_SECURE = False

# CORS settings — tests rely on override_settings to enable specific origins.
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = []

# The AI test suite must be fully offline. apps.ai.checkpointer.get_checkpointer()
# checks this and raises AssertionError instead of opening a real Postgres pool
# against config.DB_NAME (a module constant the test runner never rewrites to
# test_<db>). apps.ai.tests.CheckpointerTests deliberately exercises the real
# function body (with ConnectionPool itself mocked out) and opts back in with
# @override_settings(AI_BLOCK_REAL_CHECKPOINTER=False) per test.
AI_BLOCK_REAL_CHECKPOINTER = True

# Bump anon/user/burst ceilings high so tests don't accidentally 429 each
# other through the shared LocMemCache. Scoped rates (register/login/
# token_refresh) are preserved from base so the existing scoped-throttle
# tests (e.g. test_register_throttles_after_limit) still exercise the
# 5/min limit they expect.
REST_FRAMEWORK = {
    **_BASE_RF,
    'DEFAULT_THROTTLE_RATES': {
        **_BASE_RF['DEFAULT_THROTTLE_RATES'],
        'anon': '100000/day',
        'user': '100000/day',
        'burst': '100000/day',
        'ai': '100000/day',
        'ai-chat': '100000/day',
    },
}
