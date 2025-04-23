import logging
import random
from datetime import datetime, timedelta, timezone

from django.db.models.query import QuerySet
from shared.django_apps.reports.models import ReportSession as Upload

from services.cleanup.cleanup import run_cleanup
from services.cleanup.utils import CleanupResult, CleanupSummary, cleanup_context

log = logging.getLogger(__name__)


def run_regular_cleanup() -> CleanupSummary:
    log.info("Starting regular cleanup job")
    complete_summary = CleanupSummary(CleanupResult(0), summary={})

    cleanups_to_run = create_upload_cleanup_jobs()

    # as we expect this job to have frequent retries, and cleanup to take a long time,
    # lets shuffle the various cleanups so that each one of those makes a little progress.
    random.shuffle(cleanups_to_run)

    with cleanup_context() as context:
        for query in cleanups_to_run:
            name = query.model.__name__
            log.info(f"Cleaning up `{name}`")
            summary = run_cleanup(query, context=context)
            log.info(f"Cleaned up `{name}`", extra={"summary": summary})
            complete_summary.add(summary)

    # TODO:
    # - cleanup `Commit`s that are `deleted`
    # - figure out a way how we can first mark, and then fully delete `Branch`es

    log.info("Regular cleanup finished")
    return complete_summary


UPLOAD_RETENTION_PERIOD = 150
MONTH_SLOTS = 120


def create_upload_cleanup_jobs() -> list[QuerySet]:
    """
    This returns a list of `Upload` querysets, each targetting a subset of to-delete data.

    As the `Upload` table is one of our biggest tables, running an (almost)
    unbounded `DELETE` query would certainly cause problems.

    Fortunately though, the (production) table has an index on `created_at`,
    so queries targetting a range on that field should be fairly quick, and we
    can use that to devide up the deletion workload onto more manageable chunks.

    We are targetting 30-day chunks, going back ~10 years.
    As the main cleanup task above is using a `random.shuffle`, and the cleanup
    task itself is being restarted/retried on timeouts, this will end up with
    an even distribution of cleanup tasks running concurrently, deleting different
    chunks of this table.
    """
    latest_timestamp = datetime.now(timezone.utc) - timedelta(
        days=UPLOAD_RETENTION_PERIOD
    )
    timestamps = [latest_timestamp]
    for _ in range(MONTH_SLOTS):
        timestamps.append(timestamps[-1] - timedelta(days=30))
    timestamps.reverse()

    begin_timestamp = None
    queries: list[QuerySet] = []
    for timestamp in timestamps:
        query = Upload.objects
        if begin_timestamp:
            query = query.filter(created_at__gte=begin_timestamp)
        query = query.filter(created_at__lt=timestamp)
        queries.append(query)

        begin_timestamp = timestamp

    return queries
