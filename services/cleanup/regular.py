import logging
import random

from shared.django_apps.profiling.models import ProfilingUpload
from shared.django_apps.reports.models import ReportDetails

from services.cleanup.cleanup import run_cleanup
from services.cleanup.utils import CleanupResult, CleanupSummary, cleanup_context

log = logging.getLogger(__name__)


def run_regular_cleanup() -> CleanupSummary:
    log.info("Starting regular cleanup job")
    complete_summary = CleanupSummary(CleanupResult(0), summary={})

    # Usage of these model was removed, and we should clean up all its data before dropping the table for good.
    cleanups_to_run = [
        ReportDetails.objects.all(),
        ProfilingUpload.objects.all(),
    ]

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
    # - cleanup old `ReportSession`s (aka `Upload`s)
    # - cleanup `Commit`s that are `deleted`
    # - figure out a way how we can first mark, and then fully delete `Branch`es

    log.info("Regular cleanup finished")
    return complete_summary
