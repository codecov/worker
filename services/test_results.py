import logging
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from typing import List, Mapping, Sequence, Tuple

from shared.torngit.exceptions import TorngitClientError
from shared.yaml import UserYaml
from sqlalchemy import desc

from database.enums import ReportType
from database.models import Commit, CommitReport, RepositoryFlag, TestInstance, Upload
from services.report import BaseReportService
from services.repository import (
    fetch_and_update_pull_request_information_from_commit,
    get_repo_provider_service,
)

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


@dataclass
class TestResultsNotificationFailure:
    failure_message: str
    testsuite: str
    testname: str
    envs: List[str]
    test_id: str
    reduced_error_id: int | None


@dataclass
class TestResultsNotificationPayload:
    failed: int
    passed: int
    skipped: int
    failures: List[TestResultsNotificationFailure]
    flaky_tests: set[str] | None = None


class TestResultsNotifier:
    def __init__(
        self,
        commit: Commit,
        commit_yaml,
    ):
        self.commit = commit
        self.commit_yaml = commit_yaml

    async def get_pull(self):
        self.pull = await fetch_and_update_pull_request_information_from_commit(
            self.repo_service, self.commit, self.commit_yaml
        )

    async def send_to_provider(self, message):
        pullid = self.pull.database_pull.pullid
        try:
            comment_id = self.pull.database_pull.commentid
            if comment_id:
                await self.repo_service.edit_comment(pullid, comment_id, message)
            else:
                res = await self.repo_service.post_comment(pullid, message)
                self.pull.database_pull.commentid = res["id"]
            return True
        except TorngitClientError:
            log.error(
                "Error creating/updating PR comment",
                extra=dict(
                    commitid=self.commit.commitid,
                    pullid=pullid,
                ),
            )
            return False

    def generate_test_description(
        self,
        fail: TestResultsNotificationFailure,
    ):
        has_class_name = "\x1f" in fail.testname
        if has_class_name:
            class_name, test_name = fail.testname.split("\x1f")
            test_description = (
                f"- **Class name:** {class_name}<br>**Test name:** {test_name}"
            )
        else:
            test_description = f"- **Test name:** {fail.testname}"

        if fail.envs:
            envs = [f"  - {env}" for env in fail.envs]
            env_section = "<br>".join(envs)
            test_description = f"{test_description}\n**Flags:**\n{env_section}"

        return f"{test_description}<br><br>"

    def generate_failure_info(
        self,
        fail: TestResultsNotificationFailure,
    ):
        if fail.failure_message is not None:
            failure_message = fail.failure_message
        else:
            failure_message = "No failure message available"

        return f"  <pre>{failure_message}</pre>"

    def build_message(self, payload: TestResultsNotificationPayload) -> str:
        message = []

        message += [
            "**Test Failures Detected**: Due to failing tests, we cannot provide coverage reports at this time.",
            "",
            "### :x: Failed Test Results: ",
        ]

        completed = payload.failed + payload.passed + payload.skipped
        if payload.flaky_tests:
            num = len(payload.flaky_tests)
            flake_section = f"({num} known flakes hit)" if (num) else ""

            results = [
                f"Completed {completed} tests with **`{payload.failed} failed`**{flake_section}, {payload.passed} passed and {payload.skipped} skipped.",
            ]
            message += results
        else:
            results = f"Completed {completed} tests with **`{payload.failed} failed`**, {payload.passed} passed and {payload.skipped} skipped."
            message.append(results)

        fail_dict = defaultdict(list)
        flake_dict = defaultdict(list)
        for fail in payload.failures:
            flake = None
            if payload.flaky_tests is not None and fail.test_id in payload.flaky_tests:
                flake_dict[fail.testsuite].append(fail)
            else:
                fail_dict[fail.testsuite].append(fail)

        if fail_dict:
            message += [
                "<details><summary>View the full list of failed tests</summary>",
                "",
            ]

            self.process_dict(fail_dict, message)
            message.append("</details>")

        if flake_dict:
            message += [
                "<details><summary>View the full list of flaky tests</summary>",
                "",
            ]

            self.process_dict(flake_dict, message)
            message.append("</details>")

        return "\n".join(message)

    async def notify(self, payload: TestResultsNotificationPayload) -> Tuple[bool, str]:
        self.repo_service = get_repo_provider_service(self.commit.repository)

        await self.get_pull()
        if self.pull is None:
            log.info(
                "Not notifying since there is no pull request associated with this commit",
                extra=dict(
                    commitid=self.commit.commitid,
                ),
            )
            return False, "no_pull"

        message = self.build_message(payload)

        sent_to_provider = await self.send_to_provider(message)
        if sent_to_provider == False:
            return (False, "torngit_error")

        return (True, "comment_posted")

    def insert_breaks(self, table_value):
        line_size = 70
        lines = table_value.split("<br>")
        for i, line in enumerate(lines):
            line_with_breaks = [
                line[i : i + line_size] for i in range(0, len(line), line_size)
            ]
            lines[i] = "<br>".join(line_with_breaks)

        return "<br>".join(lines)

    async def error_comment(self):
        self.repo_service = get_repo_provider_service(self.commit.repository)

        await self.get_pull()
        if self.pull is None:
            log.info(
                "Not notifying since there is no pull request associated with this commit",
                extra=dict(
                    commitid=self.commit.commitid,
                ),
            )
            return False, "no_pull"

        message = ":x: We are unable to process any of the uploaded JUnit XML files. Please ensure your files are in the right format."

        sent_to_provider = await self.send_to_provider(message)
        if sent_to_provider == False:
            return (False, "torngit_error")

        return (True, "comment_posted")

    def process_dict(self, d, message):
        for testsuite, fail_list in d.items():
            message.append(f"## {testsuite}")
            for fail in fail_list:
                test_description = self.generate_test_description(fail)
                message.append(test_description)
                failure_information = self.generate_failure_info(fail)
                message.append(failure_information)


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
