import logging
from dataclasses import dataclass
from hashlib import sha256
from typing import List, Mapping, Sequence

from shared.yaml import UserYaml
from sqlalchemy import desc

from database.enums import ReportType
from database.models import Commit, CommitReport, RepositoryFlag, TestInstance, Upload
from helpers.notifier import BaseNotifier
from rollouts import FLAKY_SHADOW_MODE, FLAKY_TEST_DETECTION
from services.license import requires_license
from services.report import BaseReportService
from services.repository import get_repo_provider_service
from services.urls import get_members_url, get_test_analytics_url
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)


class TestResultsReportService(BaseReportService):
    def __init__(self, current_yaml: UserYaml):
        super().__init__(current_yaml)
        self.flag_dict = None

    def initialize_and_save_report(
        self, commit: Commit, report_code: str | None = None
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
        flags = normalized_arguments.get("flags") or []
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
    display_name: str
    envs: List[str]
    test_id: str
    duration_seconds: float
    build_url: str | None = None


@dataclass
class FlakeInfo:
    failed: int
    count: int


@dataclass
class TestResultsNotificationPayload:
    failed: int
    passed: int
    skipped: int
    failures: List[TestResultsNotificationFailure]
    flaky_tests: dict[str, FlakeInfo]


def wrap_in_details(summary: str, content: str):
    result = f"<details><summary>{summary}</summary>\n{content}\n</details>"
    return result


def make_quoted(content: str) -> str:
    lines = content.splitlines()

    result = ["> " + line for line in lines]

    result = "\n".join(result)
    return f"\n{result}\n"


def properly_backtick(content: str) -> str:
    max_backtick_count = 0
    curr_backtick_count = 0
    prev_char = None
    for char in content:
        if char == "`":
            curr_backtick_count += 1
        else:
            curr_backtick_count = 0

        if curr_backtick_count > max_backtick_count:
            max_backtick_count = curr_backtick_count

    backticks = "`" * (max_backtick_count + 1)
    return f"{backticks}\n{content}\n{backticks}"


def wrap_in_code(content: str) -> str:
    if "```" in content:
        return properly_backtick(content)
    else:
        return f"\n```\n{content}\n```\n"


def display_duration(f: float) -> str:
    before_dot, after_dot = str(f).split(".")
    if len(before_dot) > 3:
        return before_dot
    else:
        return f"{f:.3g}"


def generate_failure_info(
    fail: TestResultsNotificationFailure,
):
    if fail.failure_message is not None:
        failure_message = fail.failure_message
    else:
        failure_message = "No failure message available"

    failure_message = wrap_in_code(failure_message)
    if fail.build_url:
        return f"{failure_message}\n[View]({fail.build_url}) the CI Build"
    else:
        return failure_message


def generate_view_test_analytics_line(commit: Commit) -> str:
    repo = commit.repository
    test_analytics_url = get_test_analytics_url(repo, commit)
    return f"\nTo view more test analytics go to the [Test Analytics Dashboard]({test_analytics_url})\nGot feedback? Let us know on [Github](https://github.com/codecov/feedback/issues)"


def messagify_failure(
    failure: TestResultsNotificationFailure,
) -> str:
    test_name = wrap_in_code(failure.display_name.replace("\x1f", " "))
    formatted_duration = display_duration(failure.duration_seconds)
    stack_trace_summary = f"Stack Traces | {formatted_duration}s run time"
    stack_trace = wrap_in_details(
        stack_trace_summary,
        make_quoted(generate_failure_info(failure)),
    )
    return make_quoted(f"{test_name}\n{stack_trace}")


def messagify_flake(
    flaky_failure: TestResultsNotificationFailure,
    flake_info: FlakeInfo,
) -> str:
    test_name = wrap_in_code(flaky_failure.display_name.replace("\x1f", " "))
    formatted_duration = display_duration(flaky_failure.duration_seconds)
    flake_rate = flake_info.failed / flake_info.count * 100
    flake_rate_section = f"**Flake rate in main:** {flake_rate:.2f}% (Passed {flake_info.count - flake_info.failed} times, Failed {flake_info.failed} times)"
    stack_trace_summary = f"Stack Traces | {formatted_duration}s run time"
    stack_trace = wrap_in_details(
        stack_trace_summary,
        make_quoted(generate_failure_info(flaky_failure)),
    )
    return make_quoted(f"{test_name}\n{flake_rate_section}\n{stack_trace}")


@dataclass
class TestResultsNotifier(BaseNotifier):
    payload: TestResultsNotificationPayload | None = None

    def build_message(self) -> str:
        if self.payload is None:
            raise ValueError("Payload passed to notifier is None, cannot build message")

        message = []

        message.append(f"### :x: {self.payload.failed} Tests Failed:")

        completed = self.payload.failed + self.payload.passed

        message += [
            "| Tests completed | Failed | Passed | Skipped |",
            "|---|---|---|---|",
            f"| {completed} | {self.payload.failed} | {self.payload.passed} | {self.payload.skipped} |",
        ]

        failures = sorted(
            filter(
                lambda x: x.test_id not in self.payload.flaky_tests,
                self.payload.failures,
            ),
            key=lambda x: (x.duration_seconds, x.display_name),
        )

        if failures:
            failure_content = [f"{messagify_failure(failure)}" for failure in failures]

            top_3_failed_section = wrap_in_details(
                f"View the top {min(3, len(failures))} failed tests by shortest run time",
                "\n".join(failure_content),
            )

            message.append(top_3_failed_section)

        flaky_failures = list(
            filter(
                lambda x: x.test_id in self.payload.flaky_tests,
                self.payload.failures,
            ),
        )

        flake_content = [
            f"{messagify_flake(flaky_failure, self.payload.flaky_tests[flaky_failure.test_id])}"
            for flaky_failure in flaky_failures
        ]

        if flake_content:
            flaky_section = wrap_in_details(
                f"View the full list of {len(flaky_failures)} :snowflake: flaky tests",
                "\n".join(flake_content),
            )

            message.append(flaky_section)

        message.append(generate_view_test_analytics_line(self.commit))
        return "\n".join(message)

    def error_comment(self):
        self._repo_service = get_repo_provider_service(self.commit.repository)

        pull = self.get_pull()
        if pull is None:
            log.info(
                "Not notifying since there is no pull request associated with this commit",
                extra=dict(
                    commitid=self.commit.commitid,
                ),
            )
            return False, "no_pull"

        message = ":x: We are unable to process any of the uploaded JUnit XML files. Please ensure your files are in the right format."

        sent_to_provider = self.send_to_provider(pull, message)
        if sent_to_provider == False:
            return (False, "torngit_error")

        return (True, "comment_posted")

    def upgrade_comment(self):
        if self._repo_service is None:
            self._repo_service = get_repo_provider_service(self.commit.repository)

        pull = self.get_pull()
        if pull is None:
            log.info(
                "Not notifying since there is no pull request associated with this commit",
                extra=dict(
                    commitid=self.commit.commitid,
                ),
            )
            return False, "no_pull"

        db_pull = pull.database_pull
        provider_pull = pull.provider_pull
        if provider_pull is None:
            return False, "missing_provider_pull"

        link = get_members_url(db_pull)

        author_username = provider_pull["author"].get("username")

        if not requires_license():
            message = "\n".join(
                [
                    f"The author of this PR, {author_username}, is not an activated member of this organization on Codecov.",
                    f"Please [activate this user on Codecov]({link}) to display this PR comment.",
                    "Coverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.",
                    "Please don't hesitate to email us at support@codecov.io with any questions.",
                ]
            )
        else:
            message = "\n".join(
                [
                    f"The author of this PR, {author_username}, is not activated in your Codecov Self-Hosted installation.",
                    f"Please [activate this user]({link}) to display this PR comment.",
                    "Coverage data is still being uploaded to Codecov Self-Hosted for the purposes of overall coverage calculations.",
                    "Please contact your Codecov On-Premises installation administrator with any questions.",
                ]
            )

        sent_to_provider = self.send_to_provider(pull, message)
        if sent_to_provider == False:
            return (False, "torngit_error")

        return (True, "comment_posted")


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


def should_write_flaky_detection(repoid: int, commit_yaml: UserYaml) -> bool:
    return (
        FLAKY_TEST_DETECTION.check_value(identifier=repoid, default=False)
        or FLAKY_SHADOW_MODE.check_value(identifier=repoid, default=False)
    ) and read_yaml_field(commit_yaml, ("test_analytics", "flake_detection"), True)


def should_read_flaky_detection(repoid: int, commit_yaml: UserYaml) -> bool:
    return FLAKY_TEST_DETECTION.check_value(
        identifier=repoid, default=False
    ) and read_yaml_field(commit_yaml, ("test_analytics", "flake_detection"), True)
