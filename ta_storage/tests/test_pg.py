from database.models import DailyTestRollup, Test, TestFlagBridge, TestInstance
from database.tests.factories import RepositoryFlagFactory, UploadFactory
from ta_storage.pg import PGDriver


def test_pg_driver(dbsession):
    pg = PGDriver(dbsession, set())

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

    pg.write_testruns(
        upload.report.commit.repoid,
        upload.report.commit.id,
        upload.report.commit.branch,
        upload,
        "pytest",
        [
            {
                "name": "test_name",
                "classname": "test_class",
                "testsuite": "test_suite",
                "duration": 100.0,
                "outcome": "passed",
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
                "outcome": "failed",
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
