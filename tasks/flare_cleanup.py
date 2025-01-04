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

    def run_cron_task(self, db_session, batch_size=1000, limit=10000, *args, **kwargs):
        # for any Pull that is not OPEN, clear the flare field(s), targeting older data
        non_open_pulls = Pull.objects.exclude(state=PullStates.OPEN.value).order_by(
            "updatestamp"
        )

        log.info("Starting FlareCleanupTask")

        # clear in db
        non_open_pulls_with_flare_in_db = non_open_pulls.filter(
            _flare__isnull=False
        ).exclude(_flare={})

        # Process in batches
        total_updated = 0
        start = 0
        while start < limit:
            stop = start + batch_size if start + batch_size < limit else limit
            batch = non_open_pulls_with_flare_in_db.values_list("id", flat=True)[
                start:stop
            ]
            if not batch:
                break
            n_updated = non_open_pulls_with_flare_in_db.filter(id__in=batch).update(
                _flare=None
            )
            total_updated += n_updated
            start = stop

        log.info(f"FlareCleanupTask cleared {total_updated} database flares")

        # clear in Archive
        non_open_pulls_with_flare_in_archive = non_open_pulls.filter(
            _flare_storage_path__isnull=False
        )

        # Process archive deletions in batches
        total_updated = 0
        start = 0
        while start < limit:
            stop = start + batch_size if start + batch_size < limit else limit
            batch = non_open_pulls_with_flare_in_archive.values_list("id", flat=True)[
                start:stop
            ]
            if not batch:
                break
            flare_paths_from_batch = Pull.objects.filter(id__in=batch).values_list(
                "_flare_storage_path", flat=True
            )
            try:
                archive_service = ArchiveService(repository=None)
                archive_service.delete_files(flare_paths_from_batch)
            except Exception as e:
                # if something fails with deleting from archive, leave the _flare_storage_path on the pull object.
                # only delete _flare_storage_path if the deletion from archive was successful.
                log.error(f"FlareCleanupTask failed to delete archive files: {e}")
                continue

            # Update the _flare_storage_path field for successfully processed pulls
            n_updated = Pull.objects.filter(id__in=batch).update(
                _flare_storage_path=None
            )
            total_updated += n_updated
            start = stop

        log.info(f"FlareCleanupTask cleared {total_updated} Archive flares")

    def manual_run(self, db_session=None, limit=1000, *args, **kwargs):
        self.run_cron_task(db_session, limit=limit, *args, **kwargs)


RegisteredFlareCleanupTask = celery_app.register_task(FlareCleanupTask())
flare_cleanup_task = celery_app.tasks[RegisteredFlareCleanupTask.name]
