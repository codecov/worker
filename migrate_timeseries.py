import os

import django
from django.core.management import call_command

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_scaffold.settings")
django.setup()

from django.conf import settings  # noqa: E402


def run_migrate_commands():
    try:
        if settings.TA_TIMESERIES_ENABLED:
            print("Running timeseries migrations")
            call_command(
                "migrate",
                database="timeseries",
                app_label="timeseries",
                settings="django_scaffold.settings",
                verbosity=1,
            )
        else:
            print("Skipping timeseries migrations")

        if settings.TA_TIMESERIES_ENABLED:
            print("Running ta_timeseries migrations")
            call_command(
                "migrate",
                database="ta_timeseries",
                app_label="ta_timeseries",
                settings="django_scaffold.settings",
                verbosity=1,
            )
        else:
            print("Skipping ta_timeseries migrations")

    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    run_migrate_commands()
