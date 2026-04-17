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


# --- Django core --------------------------------------------------------------
SECRET_KEY: str = os.environ["SECRET_KEY"]
DEBUG: bool = _bool("DEBUG", default=False)

ALLOWED_HOSTS: list[str] = _csv("ALLOWED_HOSTS")
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

ADMIN_URL: str = os.getenv("ADMIN_URL", "admin/")

# --- Database -----------------------------------------------------------------
DB_NAME: str = os.environ["DB_NAME"]
DB_USER: str = os.environ["DB_USER"]
DB_PASSWORD: str = os.environ["DB_PASSWORD"]
DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_PORT: str = os.getenv("DB_PORT", "5432")
