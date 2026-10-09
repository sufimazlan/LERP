"""Django settings for LERP. Everything environment-specific comes from environment variables."""

import os
from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DJANGO_DEBUG")
SECRET_KEY = env("DJANGO_SECRET_KEY") or ("insecure-dev-only-key" if DEBUG else "")
if not SECRET_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY (or DJANGO_DEBUG=1 for local development).")

ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")]
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS").split(",") if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "lerp.tenancy",
    "lerp.audit",
    "lerp.approvals",
    "lerp.ai",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "lerp.tenancy.middleware.TenantMiddleware",
]

ROOT_URLCONF = "lerp.urls"
WSGI_APPLICATION = "lerp.wsgi.application"

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

# The app connects as a role that can't own tables or bypass row-level security.
# Migrations run separately as the schema owner (see docker-entrypoint.sh).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "lerp"),
        "USER": env("DB_USER", "lerp"),
        "PASSWORD": env("DB_PASSWORD", "lerp"),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
        "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("ms", "Bahasa Melayu")]
TIME_ZONE = "Asia/Kuala_Lumpur"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Set both in production, where a TLS-terminating proxy sits in front of the app.
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT")
SECURE_HSTS_SECONDS = int(env("DJANGO_SECURE_HSTS_SECONDS", "0"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# AI gateway (docs/architecture-plan.md sections 5.2 and 7). AI is off for every tenant
# until a tenant admin turns it on and sets a monthly budget.
LERP_AI = {
    # Provider names registered with lerp.ai.gateway.register_provider(); empty = none.
    "HOSTED_PROVIDER": env("LERP_AI_HOSTED_PROVIDER"),
    "LOCAL_PROVIDER": env("LERP_AI_LOCAL_PROVIDER"),
    # The cheapest capable model is the default; escalate per task only when evaluations demand it.
    "HOSTED_MODEL": env("LERP_AI_HOSTED_MODEL", "claude-haiku-5-5"),
    "LOCAL_MODEL": env("LERP_AI_LOCAL_MODEL"),
    "USD_TO_MYR": Decimal(env("LERP_USD_TO_MYR", "4.10")),
    # US$ per million tokens (input, output), from section 9.4 of the plan (checked 9 Oct 2026).
    # Haiku prices apply to prompts up to 100k tokens. A hosted model without a price is refused,
    # so no spend goes unmetered.
    "PRICES_USD_PER_MTOK": {
        "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
        "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    },
}
