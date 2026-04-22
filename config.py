"""Centralized environment configuration.

Reads values from the process environment (with `.env` fallback) once at
import time so the rest of the codebase can import plain Python constants
instead of sprinkling `os.getenv()` calls throughout.

Required variables raise `KeyError` at import time if missing — that is
deliberate: a missing `SECRET_KEY` should crash startup, not produce a
running server with an undefined signing key.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


def _csv(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def _proxy_header(name: str) -> tuple[str, str] | None:
    raw = os.getenv(name)
    if not raw or "=" not in raw:
        return None
    header, value = raw.split("=", 1)
    return (header.strip(), value.strip())


# --- Django core --------------------------------------------------------------
SECRET_KEY: str = os.environ["SECRET_KEY"]
DEBUG: bool = _bool("DEBUG", default=False)

ALLOWED_HOSTS: list[str] = _csv("ALLOWED_HOSTS")
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

ADMIN_URL: str = os.getenv("ADMIN_URL", "admin/")

# --- CORS ---------------------------------------------------------------------
CORS_ALLOWED_ORIGINS: list[str] = _csv("CORS_ALLOWED_ORIGINS")
# When running DEBUG and no origins are explicitly allowed, open CORS for local dev.
CORS_ALLOW_ALL_ORIGINS: bool = DEBUG and not CORS_ALLOWED_ORIGINS

# --- Production security headers ---------------------------------------------
SECURE_SSL_REDIRECT: bool = _bool("SECURE_SSL_REDIRECT", default=False)
SECURE_HSTS_SECONDS: int = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS: bool = _bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True
)
SECURE_HSTS_PRELOAD: bool = _bool("SECURE_HSTS_PRELOAD", default=True)
SECURE_PROXY_SSL_HEADER: tuple[str, str] | None = _proxy_header(
    "SECURE_PROXY_SSL_HEADER"
)
CSRF_TRUSTED_ORIGINS: list[str] = _csv("CSRF_TRUSTED_ORIGINS")
SESSION_COOKIE_SECURE: bool = _bool("SESSION_COOKIE_SECURE", default=not DEBUG)
CSRF_COOKIE_SECURE: bool = _bool("CSRF_COOKIE_SECURE", default=not DEBUG)

# --- Database -----------------------------------------------------------------
DB_NAME: str = os.environ["DB_NAME"]
DB_USER: str = os.environ["DB_USER"]
DB_PASSWORD: str = os.environ["DB_PASSWORD"]
DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_PORT: str = os.getenv("DB_PORT", "5432")
