import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_scaffold.settings")
django.setup()


if __name__ == "__main__":
    # from one_off_scripts.backfill_daily_test_rollups import run_impl
    from one_off_scripts.rerun_uploads import rerun_test_results_uploads

    rerun_test_results_uploads("2024-09-25", "2024-09-27")

    # run_impl()
    # backfill_test_flag_bridges()
