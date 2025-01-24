import logging
from dataclasses import dataclass
from hashlib import sha256

from shared.plan.constants import FREE_PLAN_REPRESENTATIONS, TEAM_PLAN_REPRESENTATIONS
from shared.yaml import UserYaml
from sqlalchemy import desc, distinct, func
from sqlalchemy.orm import Session, joinedload

from database.models import (
    Commit,
    Repository,
    TestInstance,
    Upload,
    UploadError,
)
from helpers.notifier import BaseNotifier
from rollouts import FLAKY_TEST_DETECTION
from services.license import requires_license
from services.urls import get_members_url, get_test_analytics_url
from services.yaml import read_yaml_field

log = logging.getLogger(__name__)


def generate_flags_hash(flag_names: list[str]) -> str:
    return sha256((" ".join(sorted(flag_names))).encode("utf-8")).hexdigest()


def generate_test_id(repoid, testsuite, name, flags_hash):
    return sha256(
        (" ".join([str(x) for x in [repoid, testsuite, name, flags_hash]])).encode(
            "utf-8"
        )
    ).hexdigest()


def latest_failures_for_commit(
    db_session: Session, repo_id: int, commit_sha: str
) -> list[TestInstance]:
    """
    This will result in a SQL query that looks something like this:

    SELECT DISTINCT ON (rti.test_id) rti.id, ...
    FROM reports_testinstance rti
    JOIN reports_upload ru ON ru.id = rti.upload_id
    LEFT OUTER JOIN reports_test rt ON rt.id = rti.test_id
    WHERE ...
    ORDER BY rti.test_id, ru.created_at DESC

    The goal of this query is to return:
    > the latest test instance failure for each unique test based on upload creation time

    The `DISTINCT ON` test_id with the order by test_id, enforces that we are only fetching one test instance for each test.

    The ordering by `upload.create_at DESC` enforces that we get the latest test instance for that unique test.
    """

    return (
        db_session.query(TestInstance)
        .join(TestInstance.upload)
        .options(joinedload(TestInstance.test))
        .filter(TestInstance.repoid == repo_id, TestInstance.commitid == commit_sha)
        .filter(TestInstance.outcome.in_(["failure", "error"]))
        .order_by(TestInstance.test_id)
        .order_by(desc(Upload.created_at))
        .distinct(TestInstance.test_id)
        .all()
    )


def get_test_summary_for_commit(
    db_session: Session, repo_id: int, commit_sha: str
) -> dict[str, int]:
    return dict(
        db_session.query(
            TestInstance.outcome, func.count(distinct(TestInstance.test_id))
        )
        .filter(TestInstance.repoid == repo_id, TestInstance.commitid == commit_sha)
        .group_by(TestInstance.outcome)
        .all()
    )


@dataclass
class FlakeInfo:
    failed: int
    count: int


@dataclass
class TestFailure:
    display_name: str
    failure_message: str | None
    duration_seconds: float
    build_url: str | None
    flake_info: FlakeInfo | None = None


@dataclass
class TestResultsNotificationPayload:
    failed: int
    passed: int
    skipped: int
    regular_failures: list[TestFailure] | None = None
    flaky_failures: list[TestFailure] | None = None


def wrap_in_details(summary: str, content: str):
    result = f"<details><summary>{summary}</summary>\n{content}\n</details>"
    return result


def make_quoted(content: str) -> str:
    lines = content.splitlines()
    result = "\n".join("> " + line for line in lines)
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
    return f"{backticks}python\n{content}\n{backticks}"


def wrap_in_code(content: str) -> str:
    if "```" in content:
        return properly_backtick(content)
    else:
        return f"\n```python\n{content}\n```\n"


def display_duration(f: float) -> str:
    before_dot, after_dot = str(f).split(".")
    if len(before_dot) > 3:
        return before_dot
    else:
        return f"{f:.3g}"


def generate_failure_info(
    fail: TestFailure,
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
    return f"\nTo view more test analytics, go to the [Test Analytics Dashboard]({test_analytics_url})\n:loudspeaker:  Thoughts on this report? [Let us know!](https://github.com/codecov/feedback/issues/304)"


def messagify_failure(
    failure: TestFailure,
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
    failure: TestFailure,
) -> str:
    test_name = wrap_in_code(failure.display_name.replace("\x1f", " "))
    formatted_duration = display_duration(failure.duration_seconds)
    assert failure.flake_info is not None
    flake_rate = failure.flake_info.failed / failure.flake_info.count * 100
    flake_rate_section = f"**Flake rate in main:** {flake_rate:.2f}% (Passed {failure.flake_info.count - failure.flake_info.failed} times, Failed {failure.flake_info.failed} times)"
    stack_trace_summary = f"Stack Traces | {formatted_duration}s run time"
    stack_trace = wrap_in_details(
        stack_trace_summary,
        make_quoted(generate_failure_info(failure)),
    )
    return make_quoted(f"{test_name}\n{flake_rate_section}\n{stack_trace}")


def specific_error_message(upload_error: UploadError) -> str:
    title = f"### :x: {upload_error.error_code}"
    if upload_error.error_code == "Unsupported file format":
        description = "\n".join(
            [
                "Upload processing failed due to unsupported file format. Please review the parser error message:",
                f"`{upload_error.error_params['error_message']}`",
                "For more help, visit our [troubleshooting guide](https://docs.codecov.com/docs/test-analytics#troubleshooting).",
            ]
        )
    elif upload_error.error_code == "File not found":
        description = "\n".join(
            [
                "No result to display due to the CLI not being able to find the file.",
                "Please ensure the file contains `junit` in the name and automated file search is enabled,",
                "or the desired file specified by the `file` and `search_dir` arguments of the CLI.",
            ]
        )
    else:
        raise ValueError("Unrecognized error code")
    message = [
        title,
        make_quoted(description),
    ]
    return "\n".join(message)


@dataclass
class TestResultsNotifier(BaseNotifier):
    payload: TestResultsNotificationPayload | None = None
    error: UploadError | None = None

    def build_message(self) -> str:
        if self.payload is None:
            raise ValueError("Payload passed to notifier is None, cannot build message")

        message = []

        if self.error:
            message.append(specific_error_message(self.error))

        if self.error and (
            self.payload.regular_failures or self.payload.flaky_failures
        ):
            message.append("---")

        if self.payload.regular_failures or self.payload.flaky_failures:
            message.append(f"### :x: {self.payload.failed} Tests Failed:")

            completed = self.payload.failed + self.payload.passed

            message += [
                "| Tests completed | Failed | Passed | Skipped |",
                "|---|---|---|---|",
                f"| {completed} | {self.payload.failed} | {self.payload.passed} | {self.payload.skipped} |",
            ]

            if self.payload.regular_failures:
                failures = sorted(
                    self.payload.regular_failures,
                    key=lambda x: (x.duration_seconds, x.display_name),
                )[:3]
                failure_content = [
                    f"{messagify_failure(failure)}" for failure in failures
                ]

                top_3_failed_section = wrap_in_details(
                    f"View the top {min(3, len(failures))} failed tests by shortest run time",
                    "\n".join(failure_content),
                )

                message.append(top_3_failed_section)

            if self.payload.regular_failures and self.payload.flaky_failures:
                message.append("---")

            if self.payload.flaky_failures:
                flaky_failures = self.payload.flaky_failures
                if flaky_failures:
                    flake_content = [
                        f"{messagify_flake(failure)}" for failure in flaky_failures
                    ]

                    flaky_section = wrap_in_details(
                        f"View the full list of {len(flaky_failures)} :snowflake: flaky tests",
                        "\n".join(flake_content),
                    )

                    message.append(flaky_section)

        message.append(generate_view_test_analytics_line(self.commit))
        return "\n".join(message)

    def error_comment(self):
        """
        This is no longer used in the new TA finisher task, but this is what used to display the error comment
        """
        message: str

        if self.error is None:
            message = ":x: We are unable to process any of the uploaded JUnit XML files. Please ensure your files are in the right format."
        else:
            message = specific_error_message(self.error)

        pull = self.get_pull()
        if pull is None:
            return False, "no_pull"

        sent_to_provider = self.send_to_provider(pull, message)

        if sent_to_provider is False:
            return (False, "torngit_error")

        return (True, "comment_posted")

    def upgrade_comment(self):
        pull = self.get_pull()
        if pull is None:
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


def not_private_and_free_or_team(repo: Repository):
    return not (
        repo.private
        and repo.owner.plan
        in {**FREE_PLAN_REPRESENTATIONS, **TEAM_PLAN_REPRESENTATIONS}
    )


def should_do_flaky_detection(repo: Repository, commit_yaml: UserYaml) -> bool:
    has_flaky_configured = read_yaml_field(
        commit_yaml, ("test_analytics", "flake_detection"), True
    )
    feature_enabled = FLAKY_TEST_DETECTION.check_value(
        identifier=repo.repoid, default=True
    )
    has_valid_plan_repo_or_owner = not_private_and_free_or_team(repo)
    return has_flaky_configured and (feature_enabled or has_valid_plan_repo_or_owner)
