"""Production settings — strict defaults, fail-fast on misconfiguration."""
import os

import config
from .base import *  # noqa: F401,F403

DEBUG = False

# All env-driven — REQUIRED to be set, checked below.
ALLOWED_HOSTS = config.ALLOWED_HOSTS
CORS_ALLOWED_ORIGINS = config.CORS_ALLOWED_ORIGINS
CORS_ALLOW_ALL_ORIGINS = False
CSRF_TRUSTED_ORIGINS = config.CSRF_TRUSTED_ORIGINS
SECURE_PROXY_SSL_HEADER = config.SECURE_PROXY_SSL_HEADER

# Prod-safe defaults: on unless env explicitly turns them off.
SECURE_SSL_REDIRECT = (
    config.SECURE_SSL_REDIRECT
    if "SECURE_SSL_REDIRECT" in os.environ
    else True
)
SECURE_HSTS_SECONDS = config.SECURE_HSTS_SECONDS or 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = config.SECURE_HSTS_INCLUDE_SUBDOMAINS
SECURE_HSTS_PRELOAD = config.SECURE_HSTS_PRELOAD

# Hardcoded True — cookies over HTTPS only.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Fail-fast on misconfiguration. Clearer than a silent bad-deploy.
assert not DEBUG, "DEBUG must be False in production"
assert ALLOWED_HOSTS, "ALLOWED_HOSTS must not be empty in production"
assert SECRET_KEY and len(SECRET_KEY) >= 50, (
    "SECRET_KEY must be at least 50 chars in production"
)

# Minimal stderr logging — structured logging / Sentry come later.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "apps": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
