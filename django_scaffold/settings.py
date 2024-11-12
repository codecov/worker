import os
from pathlib import Path

from shared.django_apps.db_settings import *

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

ALLOWED_HOSTS = []

DATABASES["default"]["AUTOCOMMIT"] = False
if "timeseries" in DATABASES:
    DATABASES["timeseries"]["AUTOCOMMIT"] = False

IS_DEV = os.getenv("RUN_ENV") == "DEV"

GCS_BUCKET_NAME = get_config("services", "minio", "bucket")

# Application definition
INSTALLED_APPS = [
    "shared.django_apps.legacy_migrations",
    "shared.django_apps.codecov_auth",
    "shared.django_apps.core",
    "shared.django_apps.reports",
    "shared.django_apps.pg_telemetry",
    "shared.django_apps.rollouts",
    "shared.django_apps.user_measurements",
    "shared.django_apps.bundle_analysis",
    "psqlextra",
    # Needed to install legacy migrations
    "django.contrib.admin",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.messages",
    "django.contrib.sessions",
]

TELEMETRY_VANILLA_DB = "default"
TELEMETRY_TIMESCALE_DB = "timeseries"

SKIP_RISKY_MIGRATION_STEPS = get_config("migrations", "skip_risky_steps", default=False)

MIDDLEWARE = [
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]

BUNDLE_ANALYSIS_NOTIFY_MESSAGE_TEMPLATES = (
    BASE_DIR / "services" / "bundle_analysis" / "notify" / "messages" / "templates"
)
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BUNDLE_ANALYSIS_NOTIFY_MESSAGE_TEMPLATES],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = []

# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True
