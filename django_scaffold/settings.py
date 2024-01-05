import os
from pathlib import Path

from shared.django_apps.db_settings import *

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

ALLOWED_HOSTS = []

DATABASES["default"]["AUTOCOMMIT"] = True

IS_DEV = os.getenv("RUN_ENV") == "DEV"

# Application definition

INSTALLED_APPS = [
    "django_scaffold",  # must be first to override migrate command
    "shared.django_apps.pg_telemetry",
    "shared.django_apps.ts_telemetry",
]

TELEMETRY_VANILLA_DB = "default"
TELEMETRY_TIMESCALE_DB = "timeseries"

# DATABASE_ROUTERS = [
#    "database.TelemetryDatabaseRouter",
#    "shared.django_apps.db_routers.MultiDatabaseRouter",
# ]

MIDDLEWARE = []

TEMPLATES = []

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = []


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True
