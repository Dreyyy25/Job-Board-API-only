"""Development settings — loose defaults optimized for local iteration."""
from .base import *  # noqa: F401,F403

DEBUG = True

# Any host goes in dev; never use '*' in prod.
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '*']

# CORS wide-open for local frontend dev.
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGINS = []

# Security toggles OFF — dev is plain HTTP.
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Print emails to stdout instead of sending.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
