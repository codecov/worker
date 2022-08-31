from app import celery_app
from tasks.add_to_sendgrid_list import add_to_sendgrid_list_task
from tasks.commit_update import commit_update_task
from tasks.compute_comparison import compute_comparison_task
from tasks.delete_owner import delete_owner_task
from tasks.flush_repo import flush_repo
from tasks.github_marketplace import ghm_sync_plans_task
from tasks.hourly_check import hourly_check_task
from tasks.label_analysis import label_analysis_task
from tasks.mutation_test_upload import mutation_test_upload_task
from tasks.new_user_activated import new_user_activated_task
from tasks.notify import notify_task
from tasks.plan_manager_task import daily_plan_manager_task_name
from tasks.profiling_find_uncollected import find_untotalized_profilings_task
from tasks.profiling_normalizer import profiling_normalizer_task
from tasks.send_email import send_email
from tasks.static_analysis_suite_check import static_analysis_suite_check_task
from tasks.status_set_error import status_set_error_task
from tasks.status_set_pending import status_set_pending_task
from tasks.sync_pull import pull_sync_task
from tasks.sync_repos import sync_repos_task
from tasks.sync_teams import sync_teams_task
from tasks.timeseries_backfill import (
    timeseries_backfill_commits_task,
    timeseries_backfill_dataset_task,
)
from tasks.upload import upload_task
from tasks.upload_finisher import upload_finisher_task
from tasks.upload_processor import upload_processor_task
