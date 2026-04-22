"""Test settings — fast password hashing, loose host list, no SSL redirect."""
from .base import *  # noqa: F401,F403

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

# CORS settings — tests rely on override_settings to enable specific origins.
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = []
