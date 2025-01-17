from database.models import DailyTestRollup, Test, TestFlagBridge, TestInstance
from database.tests.factories import (
    RepositoryFlagFactory,
    UploadFactory,
)
from database.tests.factories.reports import TestFactory, TestInstanceFactory
from ta_storage.pg import PGDriver


def test_pg_driver(dbsession):
    upload = UploadFactory()
    dbsession.add(upload)
    dbsession.flush()

    repo_flag_1 = RepositoryFlagFactory(
        repository=upload.report.commit.repository, flag_name="flag1"
    )
    repo_flag_2 = RepositoryFlagFactory(
        repository=upload.report.commit.repository, flag_name="flag2"
    )
    dbsession.add(repo_flag_1)
    dbsession.add(repo_flag_2)
    dbsession.flush()

    upload.flags.append(repo_flag_1)
    upload.flags.append(repo_flag_2)
    dbsession.flush()

    pg = PGDriver(upload.report.commit.repoid, dbsession, None)
    pg.write_testruns(
        None,
        upload.report.commit.id,
        upload.report.commit.branch,
        upload.id_,
        upload.flag_names,
        "pytest",
        [
            {
                "name": "test_name",
                "classname": "test_class",
                "testsuite": "test_suite",
                "duration": 100.0,
                "outcome": "pass",
                "build_url": "https://example.com/build/123",
                "filename": "test_file",
                "computed_name": "test_computed_name",
                "failure_message": None,
            },
            {
                "name": "test_name2",
                "classname": "test_class2",
                "testsuite": "test_suite2",
                "duration": 100.0,
                "outcome": "failure",
                "build_url": "https://example.com/build/123",
                "filename": "test_file2",
                "computed_name": "test_computed_name2",
                "failure_message": "test_failure_message",
            },
        ],
    )

    assert dbsession.query(Test).count() == 2
    assert dbsession.query(TestInstance).count() == 2
    assert dbsession.query(TestFlagBridge).count() == 4
    assert dbsession.query(DailyTestRollup).count() == 2


def test_pg_driver_pr_comment_agg(dbsession):
    # Create test data
    upload = UploadFactory()
    dbsession.add(upload)
    dbsession.flush()

    test = TestFactory(
        repoid=upload.report.commit.repoid,
        name="test_name",
        testsuite="test_suite",
        computed_name="test_computed_name",
    )
    dbsession.add(test)
    dbsession.flush()

    test_instance = TestInstanceFactory(
        test=test,
        upload=upload,
        outcome="pass",
        commitid=upload.report.commit.commitid,
        branch=upload.report.commit.branch,
        repoid=upload.report.commit.repoid,
    )
    dbsession.add(test_instance)
    dbsession.flush()

    test_instance_2 = TestInstanceFactory(
        test=test,
        upload=upload,
        outcome="failure",
        commitid=upload.report.commit.commitid,
        branch=upload.report.commit.branch,
        repoid=upload.report.commit.repoid,
    )
    dbsession.add(test_instance_2)
    dbsession.flush()

    test_instance_3 = TestInstanceFactory(
        test=test,
        upload=upload,
        outcome="skip",
        commitid=upload.report.commit.commitid,
        branch=upload.report.commit.branch,
        repoid=upload.report.commit.repoid,
    )
    dbsession.add(test_instance_3)
    dbsession.flush()

    pg = PGDriver(upload.report.commit.repoid, dbsession, None)
    result = pg.pr_comment_agg(upload.report.commit.commitid)

    assert result == {
        "commit_sha": upload.report.commit.commitid,
        "passed_ct": 1,
        "failed_ct": 1,
        "skipped_ct": 1,
        "flaky_failed_ct": 0,
    }


def test_pg_driver_pr_comment_fail(dbsession):
    # Create test data
    upload = UploadFactory()
    dbsession.add(upload)
    upload.id_ = 3
    dbsession.flush()

    test = TestFactory(
        repoid=upload.report.commit.repoid,
        name="test_name",
        testsuite="test_suite",
        computed_name="test_computed_name",
    )
    dbsession.add(test)
    dbsession.flush()

    test_instance = TestInstanceFactory(
        test=test,
        upload=upload,
        outcome="failure",
        failure_message="Test failed with error",
        commitid=upload.report.commit.commitid,
        branch=upload.report.commit.branch,
        repoid=upload.report.commit.repoid,
    )
    dbsession.add(test_instance)
    dbsession.flush()

    pg = PGDriver(upload.report.commit.repoid, dbsession, None)
    result = pg.pr_comment_fail(upload.report.commit.commitid)

    assert result == [
        {
            "computed_name": "test_computed_name",
            "duration_seconds": 1.5,
            "failure_message": "Test failed with error",
            "id": "id_1",
            "upload_id": 3,
        }
    ]
