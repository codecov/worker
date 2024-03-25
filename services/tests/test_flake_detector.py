from uuid import uuid4

from test_results_parser import Outcome

from database.enums import FlakeSymptomType
from database.models.core import Repository
from database.models.reports import Test, TestInstance
from database.tests.factories import CommitFactory, ReportFactory, UploadFactory
from services.flake_detection import (
    DefaultBranchFailureDetector,
    DiffOutcomeDetector,
    FlakeDetectionEngine,
    UnrelatedMatchesDetector,
)
from services.test_results import generate_test_id


def create_repo(dbsession):
    r = Repository()
    dbsession.add(r)
    dbsession.flush()
    r.branch = "main"
    dbsession.flush()
    return r.repoid


def create_commit(dbsession, repoid, branch):
    c = CommitFactory()
    dbsession.add(c)
    dbsession.flush()
    c.repoid = repoid
    c.branch = branch
    dbsession.flush()
    return c.id_


def create_report(dbsession, commit_id):
    cr = ReportFactory()
    dbsession.add(cr)
    dbsession.flush()
    cr.commit_id = commit_id
    dbsession.flush()
    return cr.id_


def create_upload(dbsession, report_id):
    u = UploadFactory()
    dbsession.add(u)
    dbsession.flush()

    u.report_id = report_id
    dbsession.flush()

    return u.id_


def create_test(
    dbsession,
    repoid,
):
    name = str(uuid4())
    testsuite = str(uuid4())
    id_ = generate_test_id(repoid, testsuite, name, "")
    t = Test(
        id_=id_,
        repoid=repoid,
        testsuite=testsuite,
        name=name,
        flags_hash="",
    )
    dbsession.add(t)
    dbsession.flush()
    return id_


def create_test_instance(dbsession, test_id, upload_id, outcome, failure_message):
    ti = TestInstance(
        test_id=test_id,
        outcome=outcome,
        failure_message=failure_message,
        upload_id=upload_id,
        duration_seconds=1,
    )
    dbsession.add(ti)
    dbsession.flush()
    return ti


def test_flake_detector_failure_on_main(dbsession):
    repoid = create_repo(
        dbsession,
    )
    commitid = create_commit(dbsession, repoid, "main")
    reportid = create_report(dbsession, commitid)
    uploadid = create_upload(dbsession, reportid)
    test_id = create_test(dbsession, repoid)
    ti = create_test_instance(
        dbsession, test_id, uploadid, str(Outcome.Failure), "failure message"
    )

    dbfd = DefaultBranchFailureDetector(dbsession, repoid, "main")
    umd = UnrelatedMatchesDetector()
    dod = DiffOutcomeDetector()

    fd = FlakeDetectionEngine(dbsession, repoid, [dbfd, dod, umd], None)
    flaky_tests = fd.detect_flakes()

    assert test_id in flaky_tests
    assert ti in flaky_tests[test_id]
    assert flaky_tests[test_id][ti] == [FlakeSymptomType.FAILED_IN_DEFAULT_BRANCH]


def test_flake_consecutive_differing_outcomes(dbsession):
    repoid = create_repo(
        dbsession,
    )
    commitid = create_commit(dbsession, repoid, "not_main")
    reportid = create_report(dbsession, commitid)
    reportid2 = create_report(dbsession, commitid)
    uploadid = create_upload(dbsession, reportid)
    uploadid2 = create_upload(dbsession, reportid2)
    test_id = create_test(dbsession, repoid)
    ti1 = create_test_instance(
        dbsession, test_id, uploadid, str(Outcome.Failure), "failure message"
    )
    _ = create_test_instance(dbsession, test_id, uploadid2, str(Outcome.Pass), None)

    dbfd = DefaultBranchFailureDetector(dbsession, repoid, "main")
    umd = UnrelatedMatchesDetector()
    dod = DiffOutcomeDetector()

    fd = FlakeDetectionEngine(dbsession, repoid, [dbfd, dod, umd], None)
    flaky_tests = fd.detect_flakes()

    assert test_id in flaky_tests
    assert ti1 in flaky_tests[test_id]
    assert flaky_tests[test_id][ti1] == [FlakeSymptomType.CONSECUTIVE_DIFF_OUTCOMES]


def test_flake_matching_failures_on_unrelated_branches(dbsession):
    repoid = create_repo(
        dbsession,
    )
    commitid = create_commit(dbsession, repoid, "branch_1")
    reportid = create_report(dbsession, commitid)
    uploadid = create_upload(dbsession, reportid)

    commitid2 = create_commit(dbsession, repoid, "branch_2")
    reportid2 = create_report(dbsession, commitid2)
    uploadid2 = create_upload(dbsession, reportid2)

    commitid3 = create_commit(dbsession, repoid, "branch_3")
    reportid3 = create_report(dbsession, commitid3)
    uploadid3 = create_upload(dbsession, reportid3)

    test_id = create_test(dbsession, repoid)
    ti1 = create_test_instance(
        dbsession, test_id, uploadid, str(Outcome.Failure), "failure message"
    )
    ti2 = create_test_instance(
        dbsession, test_id, uploadid2, str(Outcome.Failure), "failure message"
    )
    ti3 = create_test_instance(
        dbsession, test_id, uploadid3, str(Outcome.Failure), "failure message"
    )

    dbfd = DefaultBranchFailureDetector(dbsession, repoid, "main")
    umd = UnrelatedMatchesDetector()
    dod = DiffOutcomeDetector()

    fd = FlakeDetectionEngine(dbsession, repoid, [dbfd, dod, umd], None)
    flaky_tests = fd.detect_flakes()

    assert test_id in flaky_tests
    assert ti1 in flaky_tests[test_id]
    assert ti2 in flaky_tests[test_id]
    assert ti3 in flaky_tests[test_id]

    assert flaky_tests[test_id][ti1] == [FlakeSymptomType.UNRELATED_MATCHING_FAILURES]
    assert flaky_tests[test_id][ti2] == [FlakeSymptomType.UNRELATED_MATCHING_FAILURES]
    assert flaky_tests[test_id][ti3] == [FlakeSymptomType.UNRELATED_MATCHING_FAILURES]


def test_flake_matching_failures_on_related_branches(dbsession):
    repoid = create_repo(
        dbsession,
    )
    commitid = create_commit(dbsession, repoid, "branch_1")
    reportid = create_report(dbsession, commitid)
    uploadid = create_upload(dbsession, reportid)

    commitid2 = create_commit(dbsession, repoid, "branch_1")
    reportid2 = create_report(dbsession, commitid2)
    uploadid2 = create_upload(dbsession, reportid2)

    commitid3 = create_commit(dbsession, repoid, "branch_1")
    reportid3 = create_report(dbsession, commitid3)
    uploadid3 = create_upload(dbsession, reportid3)

    test_id = create_test(dbsession, repoid)
    create_test_instance(
        dbsession, test_id, uploadid, str(Outcome.Failure), "failure message"
    )
    create_test_instance(
        dbsession, test_id, uploadid2, str(Outcome.Failure), "failure message"
    )
    create_test_instance(
        dbsession, test_id, uploadid3, str(Outcome.Failure), "failure message"
    )

    dbfd = DefaultBranchFailureDetector(dbsession, repoid, "main")
    umd = UnrelatedMatchesDetector()
    dod = DiffOutcomeDetector()

    fd = FlakeDetectionEngine(dbsession, repoid, [dbfd, dod, umd], None)
    flaky_tests = fd.detect_flakes()

    assert len(flaky_tests) == 0
