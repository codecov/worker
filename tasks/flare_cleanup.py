import logging

from shared.api_archive.archive import ArchiveService
from shared.celery_config import flare_cleanup_task_name
from shared.django_apps.core.models import Pull, PullStates

from app import celery_app
from tasks.crontasks import CodecovCronTask

log = logging.getLogger(__name__)


class FlareCleanupTask(CodecovCronTask, name=flare_cleanup_task_name):
    """
    Flare is a field on a Pull object.
    Flare is used to draw static graphs (see GraphHandler view in api) and can be large.
    The majority of flare graphs are used in pr comments, so we keep the (maybe large) flare "available"
    in either the db or Archive storage while the pull is OPEN.
    If the pull is not OPEN, we dump the flare to save space.
    If we need to generate a flare graph for a non-OPEN pull, we build_report_from_commit
    and generate fresh flare from that report (see GraphHandler view in api).
    """

    @classmethod
    def get_min_seconds_interval_between_executions(cls):
        return 72000  # 20h

    def run_cron_task(self, db_session, *args, **kwargs):
        # for any Pull that is not OPEN, clear the flare field(s)
        non_open_pulls = Pull.objects.exclude(state=PullStates.OPEN.value)

        log.info("Starting FlareCleanupTask")

        # clear in db
        non_open_pulls_with_flare_in_db = non_open_pulls.filter(
            _flare__isnull=False
        ).exclude(_flare={})
        # single query, objs are not loaded into memory, does not call .save(), does not refresh updatestamp
        n_updated = non_open_pulls_with_flare_in_db.update(_flare=None)
        log.info(f"FlareCleanupTask cleared {n_updated} _flares")

        # clear in Archive
        non_open_pulls_with_flare_in_archive = non_open_pulls.filter(
            _flare_storage_path__isnull=False
        ).select_related("repository")
        log.info(
            f"FlareCleanupTask will clear {non_open_pulls_with_flare_in_archive.count()} Archive flares"
        )
        # single query, loads all pulls and repos in qset into memory, deletes file in Archive 1 by 1
        for pull in non_open_pulls_with_flare_in_archive:
            archive_service = ArchiveService(repository=pull.repository)
            archive_service.delete_file(pull._flare_storage_path)

        # single query, objs are not loaded into memory, does not call .save(), does not refresh updatestamp
        n_updated = non_open_pulls_with_flare_in_archive.update(
            _flare_storage_path=None
        )

        log.info(f"FlareCleanupTask cleared {n_updated} Archive flares")


RegisteredFlareCleanupTask = celery_app.register_task(FlareCleanupTask())
flare_cleanup_task = celery_app.tasks[RegisteredFlareCleanupTask.name]
