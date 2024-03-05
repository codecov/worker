import logging
from hashlib import sha256
from typing import Mapping, Sequence

from shared.torngit.exceptions import TorngitClientError
from shared.yaml import UserYaml
from sqlalchemy import desc
from test_results_parser import Outcome

from database.enums import ReportType
from database.models import Commit, CommitReport, RepositoryFlag, TestInstance, Upload
from helpers.string import EscapeEnum, Replacement, StringEscaper
from services.report import BaseReportService
from services.repository import (
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)
from services.urls import get_pull_url

log = logging.getLogger(__name__)


class TestResultsReportService(BaseReportService):
    def __init__(self, current_yaml: UserYaml):
        super().__init__(current_yaml)
        self.flag_dict = None

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

        if self.flag_dict is None:
            self.fetch_repo_flags(db_session, repoid)

        for individual_flag in flag_names:
            flag_obj = self.flag_dict.get(individual_flag, None)
            if flag_obj is None:
                flag_obj = RepositoryFlag(
                    repository_id=repoid, flag_name=individual_flag
                )
                db_session.add(flag_obj)
                db_session.flush()
                self.flag_dict[individual_flag] = flag_obj
            all_flags.append(flag_obj)
        upload.flags = all_flags
        db_session.flush()
        return all_flags

    def fetch_repo_flags(self, db_session, repoid):
        existing_flags_on_repo = (
            db_session.query(RepositoryFlag).filter_by(repository_id=repoid).all()
        )
        self.flag_dict = {flag.flag_name: flag for flag in existing_flags_on_repo}


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

    async def notify(self, failures, num_passed, num_skipped, num_failed):
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
        if pull is None:
            log.info(
                "Not notifying since there is no pull request associated with this commit",
                extra=dict(
                    commitid=self.commit.commitid,
                    report_key=commit_report.external_id,
                ),
            )
            return False

        pullid = pull.database_pull.pullid

        pull_url = get_pull_url(pull.database_pull)

        message = self.build_message(
            pull_url, self.test_instances, failures, num_passed, num_skipped, num_failed
        )

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

    def build_message(
        self, url, test_instances, failures, num_passed, num_skipped, num_failed
    ):
        message = []

        message += [
            "**Test Failures Detected**: Due to failing tests, we cannot provide coverage reports at this time.",
            "",
            "### :x: Failed Test Results: ",
        ]

        results = f"Completed {len(test_instances)} tests with **`{num_failed} failed`**, {num_passed} passed and {num_skipped} skipped."

        message.append(results)

        details = [
            "<details><summary>View the full list of failed tests</summary>",
            "",
            "| **Test Description** | **Failure message** |",
            "| :-- | :-- |",
        ]

        message += details
        failure_table = [
            "| <pre>{0}</pre> | <pre>{1}</pre> |".format(
                (
                    "<br>".join(
                        self.insert_breaks(
                            f"Testsuite: {test_name.split('//////////')[0]}<br>Test name: {test_name.split('//////////')[1]}<br>Envs: {''.join(f'<br>- {test_env}' for test_env in sorted(test_env_list))}"
                        )
                        for test_name, test_env_list in sorted(
                            failed_test_to_env_list.items(),
                            key=lambda failed_test: failed_test[0],
                        )
                    )
                ),
                failure_message,
            )
            for failure_message, failed_test_to_env_list in sorted(
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


def latest_test_instances_for_a_given_commit(db_session, commit_id):
    """
    This will result in a SQL query that looks something like this:

    SELECT DISTINCT ON (rt.test_id) rt.id, rt.external_id, rt.created_at, rt.updated_at, rt.test_id, rt.duration_seconds, rt.outcome, rt.upload_id, rt.failure_message
        FROM reports_testinstance rt JOIN reports_upload ru ON ru.id = rt.upload_id JOIN reports_commitreport rc ON rc.id = ru.report_id
        WHERE rc.commit_id = <commit_id> ORDER BY rt.test_id, ru.created_at desc

    The goal of this query is to return: "the latest test instance for each unique test based on upload creation time"

    The `DISTINCT ON` test_id with the order by test_id, enforces that we are only fetching one test instance for each test

    The ordering of the upload.create_at desc enforces that we get the latest test instance for that unique test
    """
    return (
        db_session.query(TestInstance)
        .join(Upload)
        .join(CommitReport)
        .filter(
            CommitReport.commit_id == commit_id,
        )
        .order_by(TestInstance.test_id)
        .order_by(desc(Upload.created_at))
        .distinct(TestInstance.test_id)
        .all()
    )
