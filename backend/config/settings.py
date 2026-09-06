"""Django settings for DealFlow360."""

from pathlib import Path

import dj_database_url
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def env_list(key: str, default: str = "") -> list[str]:
    raw = env(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


SECRET_KEY = env("SECRET_KEY", "dev-only-not-a-real-secret")
DEBUG = env("DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    # DealFlow360 apps, in dependency order.
    "apps.accounts",
    "apps.catalog",
    "apps.governance",
    "apps.quotations",
    "apps.approvals",
    "apps.fulfillment",
    "apps.subscriptions",
    "apps.billing",
    "apps.negotiation",
    "apps.insights",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database -------------------------------------------------------------
# Supabase Postgres when DATABASE_URL is set; SQLite otherwise so nobody is
# blocked by a network problem at 2am. Same ORM, same migrations either way.
_database_url = env("DATABASE_URL")
if _database_url:
    DATABASES = {
        "default": dj_database_url.parse(
            _database_url, conn_max_age=600, conn_health_checks=True
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "dealflow.sqlite3",
            "OPTIONS": {
                # Signing in fires several API calls at once, and one of them
                # (the dashboard) sweeps deal health, which WRITES. SQLite's
                # default rollback journal gives a single writer an exclusive
                # lock over the whole file, so a concurrent reader or writer
                # got "database is locked" straight away and the dashboard
                # answered 500 — intermittently, and only ever at login, which
                # is exactly when the requests overlap.
                #
                # WAL lets readers carry on while a write is in flight, and the
                # timeout makes a second writer wait its turn rather than fail.
                # Both are per-connection pragmas, so they belong here.
                "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
                "timeout": 20,
            },
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [] if DEBUG else [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
CORS_ALLOW_CREDENTIALS = True

# --- Auth phase switch ----------------------------------------------------
# Empty => mock token backend (day 1). Set => Firebase ID token verification.
FIREBASE_CREDENTIALS_JSON = env("FIREBASE_CREDENTIALS_JSON")
USE_FIREBASE_AUTH = bool(FIREBASE_CREDENTIALS_JSON)

# Mock tokens are signed with SECRET_KEY and expire; see accounts/tokens.py.
AUTH_TOKEN_TTL_HOURS = 12
