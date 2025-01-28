import logging

from shared.django_apps.reports.models import ReportDetails

from services.cleanup.cleanup import run_cleanup

log = logging.getLogger(__name__)


def run_regular_cleanup():
    log.info("Starting regular cleanup job")

    # Usage of this model was removed, and we should clean up all its data before dropping the table for good.
    log.info("Cleaning up `ReportDetails`")
    query = ReportDetails.objects.all()
    summary = run_cleanup(query)
    log.info("Cleaned up `ReportDetails`", extra={"summary": summary})

    # TODO:
    # - cleanup old `ReportSession`s (aka `Upload`s)
    # - cleanup `Commit`s that are `deleted`
    # - figure out a way how we can first mark, and then fully delete `Branch`es

    log.info("Regular cleanup finished")
