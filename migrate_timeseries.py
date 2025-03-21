import logging
import os

import django
from django.core.management import call_command

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_scaffold.settings")
django.setup()

from django.conf import settings  # noqa: E402

logger = logging.getLogger(__name__)


def run_migrate_commands():
    try:
        if settings.TIMESERIES_ENABLED:
            logger.info("Running timeseries migrations")

            call_command(
                "migrate",
                database="timeseries",
                app_label="timeseries",
                settings="django_scaffold.settings",
                verbosity=1,
            )
        else:
            logger.info("Skipping timeseries migrations")

        if settings.TA_TIMESERIES_ENABLED:
            logger.info("Running ta_timeseries migrations")

            call_command(
                "migrate",
                database="ta_timeseries",
                app_label="ta_timeseries",
                settings="django_scaffold.settings",
                verbosity=1,
            )
        else:
            logger.info("Skipping ta_timeseries migrations")

    except Exception as e:
        logger.error(f"An error occurred: {e}")


if __name__ == "__main__":
    run_migrate_commands()
