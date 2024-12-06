from pathlib import Path

from shared.django_apps.dummy_settings import *

BASE_DIR = Path(__file__).resolve().parent.parent

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

DATABASES["default"]["TEST"] = {"NAME": "test_postgres_django"}
IS_ENTERPRISE = False
