import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_scaffold.settings")
django.setup()

if __name__ == "__main__":
    from one_off_scripts.backfill_daily_test_rollups import run_impl
    from one_off_scripts.backfill_test_flag_bridges import backfill_test_flag_bridges

    run_impl()
    backfill_test_flag_bridges()
