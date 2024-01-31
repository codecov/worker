import logging
from hashlib import sha256
from typing import Mapping, Sequence

from shared.torngit.exceptions import TorngitClientError
from test_results_parser import Outcome, Testrun

from database.enums import ReportType
from database.models import Commit, CommitReport, RepositoryFlag, Upload
from services.report import BaseReportService
from services.repository import (
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.urls import get_pull_url

log = logging.getLogger(__name__)


class TestResultsReportService(BaseReportService):
    async def initialize_and_save_report(
        self, commit: Commit, report_code: str = None
    ) -> CommitReport:
        db_session = commit.get_db_session()
        current_report_row = (
            db_session.query(CommitReport)
            .filter_by(
                commit_id=commit.id_,
                code=report_code,
                report_type=ReportType.TEST_RESULTS.value,
            )
            .first()
        )
        if not current_report_row:
            # This happens if the commit report is being created for the first time
            # or backfilled
            current_report_row = CommitReport(
                commit_id=commit.id_,
                code=report_code,
                report_type=ReportType.TEST_RESULTS.value,
            )
            db_session.add(current_report_row)
            db_session.flush()

        return current_report_row

    # support flags in test results
    def create_report_upload(
        self, normalized_arguments: Mapping[str, str], commit_report: CommitReport
    ) -> Upload:
        upload = super().create_report_upload(normalized_arguments, commit_report)
        flags = normalized_arguments.get("flags")
        flags = flags or []
        self._attach_flags_to_upload(upload, flags)
        return upload

    def _attach_flags_to_upload(self, upload: Upload, flag_names: Sequence[str]):
        """Internal function that manages creating the proper `RepositoryFlag`s and attach the sessions to them

        Args:
            upload (Upload): Description
            flag_names (Sequence[str]): Description

        Returns:
            TYPE: Description
        """
        all_flags = []
        db_session = upload.get_db_session()
        repoid = upload.report.commit.repoid
        for individual_flag in flag_names:
            existing_flag = (
                db_session.query(RepositoryFlag)
                .filter_by(repository_id=repoid, flag_name=individual_flag)
                .first()
            )
            if not existing_flag:
                existing_flag = RepositoryFlag(
                    repository_id=repoid, flag_name=individual_flag
                )
                db_session.add(existing_flag)
                db_session.flush()
            upload.flags.append(existing_flag)
            db_session.flush()
            all_flags.append(existing_flag)
        return all_flags


def generate_flags_hash(flag_names):
    return sha256((" ".join(sorted(flag_names))).encode("utf-8")).hexdigest()


def generate_test_id(repoid, testsuite, name, flags_hash):
    return sha256(
        (" ".join([str(x) for x in [repoid, testsuite, name, flags_hash]])).encode(
            "utf-8"
        )
    ).hexdigest()


class TestResultsNotifier:
    def __init__(self, commit: Commit, commit_yaml, test_instances):
        self.commit = commit
        self.commit_yaml = commit_yaml
        self.test_instances = test_instances

    async def notify(self):
        commit_report = self.commit.commit_report(report_type=ReportType.TEST_RESULTS)
        if not commit_report:
            log.warning(
                "No test results commit report found for this commit",
                extra=dict(
                    commitid=self.commit.commitid,
                    report_key=commit_report.external_id,
                ),
            )

        repo_service = get_repo_provider_service(self.commit.repository, self.commit)

        pull = await fetch_and_update_pull_request_information_from_commit(
            repo_service, self.commit, self.commit_yaml
        )
        pullid = pull.database_pull.pullid
        if pull is None:
            log.info(
                "Not notifying since there is no pull request associated with this commit",
                extra=dict(
                    commitid=self.commit.commitid,
                    report_key=commit_report.external_id,
                    pullid=pullid,
                ),
            )

        pull_url = get_pull_url(pull.database_pull)

        message = self.build_message(pull_url, self.test_instances)

        try:
            comment_id = pull.database_pull.commentid
            if comment_id:
                await repo_service.edit_comment(pullid, comment_id, message)
            else:
                res = await repo_service.post_comment(pullid, message)
                pull.database_pull.commentid = res["id"]
            return True
        except TorngitClientError:
            log.error(
                "Error creating/updating PR comment",
                extra=dict(
                    commitid=self.commit.commitid,
                    report_key=commit_report.external_id,
                    pullid=pullid,
                ),
            )
            return False

    def build_message(self, url, test_instances):
        message = []

        message += [
            f"##  [Codecov]({url}) Report",
            "",
            "**Test Failures Detected**: Due to failing tests, we cannot provide coverage reports at this time.",
            "",
            "### :x: Failed Test Results: ",
        ]
        failed_tests = 0
        passed_tests = 0
        skipped_tests = 0

        failures = dict()

        for test_instance in test_instances:
            if (
                test_instance.outcome == Outcome.Failure
                or test_instance.outcome == Outcome.Error
            ):
                failed_tests += 1
                job_code = test_instance.upload.job_code
                flag_names = sorted(test_instance.upload.flag_names)
                suffix = ""
                if job_code or flag_names:
                    suffix = f"[{''.join(flag_names) or ''} {job_code or ''}]"
                failures[
                    f"{test_instance.test.testsuite}::{test_instance.test.name}{suffix}"
                ] = test_instance.failure_message
            elif test_instance.outcome == Outcome.Skip:
                skipped_tests += 1
            elif test_instance.outcome == Outcome.Pass:
                passed_tests += 1

        results = f"Completed {len(test_instances)} tests with **`{failed_tests} failed`**, {passed_tests} passed and {skipped_tests} skipped."

        message.append(results)

        details = [
            "<details><summary>View the full list of failed tests</summary>",
            "",
            "| **File path** | **Failure message** |",
            "| :-- | :-- |",
        ]

        message += details

        failure_table = [
            "| {0} | <pre>{1}</pre> |".format(
                self.insert_breaks(failed_test_name),
                failure_message.replace("\n", "<br>"),
            )
            for failed_test_name, failure_message in sorted(
                failures.items(), key=lambda failure: failure[0]
            )
        ]

        message += failure_table

        return "\n".join(message)

    def insert_breaks(self, table_value):
        line_size = 70
        lines = [
            table_value[i : i + line_size]
            for i in range(0, len(table_value), line_size)
        ]
        return "<br>".join(lines)
