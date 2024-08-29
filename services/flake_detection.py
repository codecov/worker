from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import getLogger
from sys import getsizeof

import sentry_sdk
from test_results_parser import Outcome

from database.enums import FlakeSymptomType
from database.models.core import Commit, Repository
from database.models.reports import CommitReport, Test, TestInstance, Upload
from services.failure_normalizer import FailureNormalizer

log = getLogger(__name__)

FlakeDetectionResult = dict[Test, set[FlakeSymptomType]]


class BaseSymptomDetector:
    """
    blueprint class for a single symptom of flakiness detector

    classes that implement this interface are expected to:
    maintain their own state necessary to detect a symptom of flakiness
    in whatever form is suitable
    """

    def ingest(self, instance: TestInstance):
        """
        - receives a TestInstance as an arg
        - adds the necessary information to the state of the object
          so that the detect stage works
        """
        raise NotImplementedError()

    def detect(self) -> dict[str, TestInstance]:
        """
        Run flake detection based on all the instances that it has ingested
        for the symptom it is responsible for
        """
        raise NotImplementedError()

    def symptom(self) -> FlakeSymptomType:
        raise NotImplementedError()


class DefaultBranchFailureDetector(BaseSymptomDetector):
    def __init__(self, db_session, repoid=None, default_branch=None):
        self.instances = defaultdict(list)

        if default_branch:
            self.default_branch = default_branch
        elif repoid:
            self.default_branch = (
                db_session.query(Repository.branch)
                .filter(Repository.repoid == repoid)
                .first()
                .branch
            )
        else:
            raise ValueError()

    def ingest(self, instance):
        outcome = instance.TestInstance.outcome
        branch = instance.branch
        test_id = instance.TestInstance.test_id
        if (
            outcome == str(Outcome.Failure) or outcome == str(Outcome.Error)
        ) and branch == self.default_branch:
            self.instances[test_id].append(instance.TestInstance)

    def detect(self):
        return self.instances

    def symptom(self):
        return FlakeSymptomType.FAILED_IN_DEFAULT_BRANCH


class CommitDictObject:
    def __init__(self):
        self.outcomes = set()
        self.instances = list()


class DiffOutcomeDetector(BaseSymptomDetector):
    def __init__(self):
        self.state = defaultdict(lambda: defaultdict(CommitDictObject))
        self.res = defaultdict(list)

    def ingest(self, instance):
        test_id = instance.TestInstance.test_id
        commit_id = instance.commitid
        outcome = instance.TestInstance.outcome
        self.state[test_id][commit_id].outcomes.add(outcome)
        if outcome == str(Outcome.Failure) or outcome == str(Outcome.Error):
            self.state[test_id][commit_id].instances.append(instance.TestInstance)

    def detect(self):
        for test_id, commit_dict in self.state.items():
            for obj in commit_dict.values():
                if str(Outcome.Pass) in obj.outcomes and (
                    str(Outcome.Failure) in obj.outcomes
                    or str(Outcome.Error) in obj.outcomes
                ):
                    self.res[test_id] += obj.instances

        return self.res

    def symptom(self):
        return FlakeSymptomType.CONSECUTIVE_DIFF_OUTCOMES


@dataclass
class TestDictObject:
    def __init__(self):
        self.branches = set()
        self.instances = list()


class UnrelatedMatchesDetector(BaseSymptomDetector):
    def __init__(self, failure_normalizer: FailureNormalizer | None = None):
        self.state = defaultdict(lambda: defaultdict(TestDictObject))
        self.res = defaultdict(list)
        self.failure_normalizer = failure_normalizer

    def ingest(self, instance):
        outcome = instance.TestInstance.outcome
        if outcome == str(Outcome.Failure) or outcome == str(Outcome.Error):
            if instance.TestInstance.failure_message is not None:
                test_id = instance.TestInstance.test_id
                if self.failure_normalizer is not None:
                    fail = self.failure_normalizer.normalize_failure_message(
                        instance.TestInstance.failure_message
                    )
                else:
                    fail = instance.TestInstance.failure_message
                branch = instance.branch

                self.state[test_id][fail].branches.add(branch)
                self.state[test_id][fail].instances.append(instance.TestInstance)

    def detect(self):
        for test_id, test_dict in self.state.items():
            for obj in test_dict.values():
                if len(obj.branches) > 1:
                    self.res[test_id] += obj.instances
        return self.res

    def symptom(self):
        return FlakeSymptomType.UNRELATED_MATCHING_FAILURES


@dataclass
class FlakeEngineInstance:
    test_id: str
    outcome: str
    failure_message: str


class FlakeDetectionEngine:
    def __init__(
        self,
        db_session,
        repoid,
        symptom_detectors: list[BaseSymptomDetector],
    ):
        self.db_session = db_session
        self.repoid = repoid
        self.symptom_detectors = symptom_detectors

    @sentry_sdk.trace
    def populate(self):
        """
        Populate test_instances_ordered_by_test with:
        Test instances on a given repo that were uploaded in the past
        30 days ordered by test id

        They are ordered by test id because we want to be able to fetch
        all the test instances in one query but we want them to be separated by
        test id so we can process one test id at a time
        """
        self.test_instances_ordered_by_test = (
            self.db_session.query(
                TestInstance,
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
            .order_by(TestInstance.test_id, Commit.commitid)
            .all()
        )
        memory_used_kb = getsizeof(self.test_instances_ordered_by_test) // 1024
        sentry_sdk.metrics.gauge(
            key="flake_detection.populate.aux_memory_used",
            value=memory_used_kb,
            unit="kilobytes",
        )

    @sentry_sdk.trace
    def detect_flakes(self) -> FlakeDetectionResult:
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

        Returns a FlakeDetectionResult
        """
        self.populate()

        sentry_sdk.metrics.distribution(
            "flake_detection.detect_flakes.number_of_test_instances",
            len(self.test_instances_ordered_by_test),
            unit="test_instance",
        )
        with sentry_sdk.metrics.timing(
            "flake_detection.detect_flakes.total_time_taken"
        ):
            with sentry_sdk.metrics.timing(
                "flake_detection.detect_flakes.ingestion",
            ):
                for instance in self.test_instances_ordered_by_test:
                    for symptom_detector in self.symptom_detectors:
                        symptom_detector.ingest(instance)

            results = defaultdict(set)

            with sentry_sdk.metrics.timing(
                "flake_detection.detect_flakes.detection",
            ):
                for symptom_detector in self.symptom_detectors:
                    test_to_instance = symptom_detector.detect()
                    for test_id, instance_list in test_to_instance.items():
                        for instance in instance_list:
                            results[test_id].add(symptom_detector.symptom())

        return results
