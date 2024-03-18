from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from logging import getLogger
from sys import getsizeof
from typing import List, Set, Tuple

from sentry_sdk import metrics, trace
from test_results_parser import Outcome

from database.models.core import Commit, Repository
from database.models.reports import CommitReport, Test, TestInstance, Upload

log = getLogger(__name__)


@dataclass
class FlakeDetectionObject:
    counter: int = 0
    branch: Set[str] = field(default_factory=set)
    time: List[datetime] = field(default_factory=list)


class FlakeType(Enum):
    FailedInDefaultBranch = "FailedInDefaultBranch"
    ConsecutiveDiffOutcomes = "ConsecutiveDiffOutcomes"
    UnrelatedMatchingFailures = "UnrelatedMatchingFailures"


@dataclass
class FlakeDetectionContext:
    is_curr_flake = False
    curr_test_id = None
    flake_dict = defaultdict(FlakeDetectionObject)
    commit_to_outcome = dict()

    def reset(self, test_id):
        self.curr_test_id = test_id
        self.is_curr_flake = False
        self.flake_dict.clear()
        self.commit_to_outcome.clear()


class FlakeDetector:
    def __init__(
        self, db_session, repoid, default_branch=None, failure_normalizer=None
    ):

        self.repoid = repoid
        if default_branch:
            self.default_branch = default_branch
        else:
            self.default_branch = (
                db_session.query(Repository.branch)
                .filter(Repository.repoid == repoid)
                .first()
                .branch
            )
        self.failure_normalizer = failure_normalizer
        self.resulting_flakes = []

    @trace
    def populate(self, db_session):
        """
        Populate test_instances_ordered_by_test with:
        Test instances on a given repo that were uploaded in the past
        30 days ordered by test id

        They are ordered by test id because we want to be able to fetch
        all the test instances in one query but we want them to be separated by
        test id so we can process one test id at a time
        """
        self.test_instances_ordered_by_test = (
            db_session.query(
                TestInstance.test_id.label("test_id"),
                TestInstance.outcome,
                TestInstance.failure_message,
                Upload.created_at,
                Upload.report_id,
                Commit.branch,
                Commit.commitid,
            )
            .join(Test)
            .join(Upload, TestInstance.upload_id == Upload.id_)
            .join(CommitReport, Upload.report_id == CommitReport.id_)
            .join(Commit, CommitReport.commit_id == Commit.id_)
            .join(Repository, Repository.repoid == Test.repoid)
            .filter(
                Repository.repoid == self.repoid,
                Upload.created_at >= (datetime.now() - timedelta(days=30)),
            )
            .order_by(TestInstance.test_id)
            .all()
        )
        memory_used = getsizeof(self.test_instances_ordered_by_test)
        metrics.gauge(
            key="flake_detection.populate.aux_memory_used",
            value=memory_used,
            unit="kilobytes",
        )

    def check_if_failed_on_default(self, instance):
        if instance.branch == self.default_branch:
            self.curr_test_context.is_curr_flake = True
            self.resulting_flakes.append(
                (
                    self.curr_test_context.curr_test_id,
                    FlakeType.FailedInDefaultBranch,
                )
            )
            metrics.incr(
                "flake_detection.detect_flakes.flake_detected",
                1,
                tags={"flake_type": str(FlakeType.FailedInDefaultBranch)},
            )

    def check_if_consecutive_diff_outcomes(self, instance):
        # ignore skips
        if instance.outcome != str(Outcome.Skip):
            existing_outcome_on_commit = self.curr_test_context.commit_to_outcome.get(
                instance.commitid, None
            )
            if (
                existing_outcome_on_commit is not None
                and existing_outcome_on_commit != instance.outcome
            ):
                self.curr_test_context.is_curr_flake = True
                self.resulting_flakes.append(
                    (
                        self.curr_test_context.curr_test_id,
                        FlakeType.ConsecutiveDiffOutcomes,
                    )
                )
                metrics.incr(
                    "flake_detection.detect_flakes.flake_detected",
                    1,
                    tags={"flake_type": str(FlakeType.ConsecutiveDiffOutcomes)},
                )
            elif existing_outcome_on_commit is None:
                self.curr_test_context.commit_to_outcome[
                    instance.commitid
                ] = instance.outcome

    def check_if_failure_messages_match(self, instance):
        failure_message = instance.failure_message
        if self.failure_normalizer is not None:
            failure_message = self.failure_normalizer.normalize_failure_message(
                failure_message
            )

        self.curr_test_context.flake_dict[failure_message].counter += 1
        self.curr_test_context.flake_dict[failure_message].branch.add(instance.branch)
        self.curr_test_context.flake_dict[failure_message].time.append(
            instance.created_at.timestamp()
        )

        potential_flake = self.curr_test_context.flake_dict[failure_message]
        if potential_flake.counter > 1 and len(potential_flake.branch) > 2:
            # Exact error happened on 2 other branches at least
            self.curr_test_context.is_curr_flake = True
            self.resulting_flakes.append(
                (
                    self.curr_test_context.curr_test_id,
                    FlakeType.UnrelatedMatchingFailures,
                )
            )
            metrics.incr(
                "flake_detection.detect_flakes.flake_detected",
                1,
                tags={"flake_type": str(FlakeType.UnrelatedMatchingFailures)},
            )

    @trace
    def detect_flakes(self) -> List[Tuple[str, str]]:
        """
        Detect flaky tests on a given repo based on the test instances
        gathered in the query in the constructor

        A test is a flake if:
        - it has failed on default branch
        OR
        - it has different outcomes on different runs for the same commit
        OR
        - it has the same failure messages on failures on unrelated branches

        We check which kind of flake exists in that order


        TODO: Differentiate between random flakes and infra flakes. Infra flakes
        are flakes that are caused by a dependency or a temporary outage.
        They can be defined as: matching failure messages on unrelated branches
        clustered at a point in time, this test should only be failing for that
        range in time.

        Returns a list of tuples of flaky test id and type of flake
        """
        self.curr_test_context = FlakeDetectionContext()

        metrics.distribution(
            "flake_detection.detect_flakes.number_of_test_instances",
            len(self.test_instances_ordered_by_test),
            unit="test_instance",
        )
        with metrics.timing("flake_detection.detect_flakes.total_time_taken"):
            for instance in self.test_instances_ordered_by_test:
                with metrics.timing(
                    "flake_detection.detect_flakes.process_individual_test_instance"
                ):
                    # because the query above orders by test_id, if we see a new test
                    # we are now trying to determine if the next test is flaky
                    if instance.test_id != self.curr_test_context.curr_test_id:
                        self.curr_test_context.reset(instance.test_id)

                    # if we've already determined the current test to be a flake
                    # we don't have to keep examining instances of this test
                    if self.curr_test_context.is_curr_flake:
                        continue

                    # check if failed on default branch
                    # should probably automatically create an issue here
                    self.check_if_failed_on_default(instance)

                    # else check if consecutive fails, ignoring skips
                    self.check_if_consecutive_diff_outcomes(instance)

                    # else check if meets other requirements for flakes
                    if instance.failure_message is None:
                        continue

                    self.check_if_failure_messages_match(instance)

        return self.resulting_flakes
