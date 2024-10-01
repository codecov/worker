import datetime as dt

from celery import chord
from shared.django_apps.reports.models import (
    CommitReport,
    ReportSession,
)

from one_off_scripts.celery_stuff import create_signature


def rerun_test_results_uploads(start_date, end_date):
    relevant_reports = (
        CommitReport.objects.filter(
            created_at__gt=dt.datetime(2024, 9, 25, 0, 0, 0, 0, dt.UTC),
            created_at__lt=dt.datetime(2024, 9, 28, 0, 0, 0, 0, dt.UTC),
        )
        .select_related("testresultreporttotals")
        .filter(testresultreporttotals__isnull=True)
    )

    for report in relevant_reports:
        print(report)
        commit = report.commit
        relevant_uploads = ReportSession.objects.filter(report=report)

        print(relevant_uploads)

        chord(
            [
                create_signature(
                    "app.tasks.test_results.TestResultsProcessor",
                    kwargs=dict(
                        repoid=commit.repository_id,
                        commitid=commit.commitid,
                        commit_yaml=dict(),
                        arguments_list=[
                            {"upload_pk": upload.id} for upload in relevant_uploads
                        ],
                        report_code=None,
                    ),
                )
            ],
            create_signature(
                "app.tasks.test_results.TestResultsFinisherTask",
                kwargs=dict(
                    repoid=commit.repository_id,
                    commitid=commit.commitid,
                    commit_yaml=dict(),
                ),
            ),
        ).apply_async()
