from datetime import datetime, timedelta
from pathlib import Path

import pytest
from mock import AsyncMock
from shared.torngit.exceptions import TorngitClientError
from test_results_parser import Outcome

from database.enums import ReportType
from database.models import (
    CommitReport,
    Flake,
    ReducedError,
    Repository,
    RepositoryFlag,
    Test,
    TestInstance,
)
from database.tests.factories import (
    CommitFactory,
    OwnerFactory,
    PullFactory,
    UploadFactory,
)
from services.billing import BillingPlan
from services.repository import EnrichedPull
from services.test_results import generate_test_id
from services.urls import get_members_url
from tasks.test_results_finisher import QUEUE_NOTIFY_KEY, TestResultsFinisherTask

here = Path(__file__)


@pytest.fixture
def test_results_mock_app(mocker):
    mocked_app = mocker.patch.object(
        TestResultsFinisherTask,
        "app",
        tasks={
            "app.tasks.notify.Notify": mocker.MagicMock(),
            "app.tasks.flakes.ProcessFlakesTask": mocker.MagicMock(),
            "app.tasks.cache_rollup.CacheTestRollupsTask": mocker.MagicMock(),
        },
    )
    return mocked_app


@pytest.fixture
def mock_repo_provider_comments(mocker):
    m = mocker.MagicMock(
        edit_comment=AsyncMock(return_value=True),
        post_comment=AsyncMock(return_value={"id": 1}),
    )
    _ = mocker.patch(
        "helpers.notifier.get_repo_provider_service",
        return_value=m,
    )
    _ = mocker.patch(
        "services.test_results.get_repo_provider_service",
        return_value=m,
    )
    _ = mocker.patch(
        "tasks.test_results_finisher.get_repo_provider_service",
        return_value=m,
    )
    return m


@pytest.fixture
def test_results_setup(mocker, dbsession):
    mocker.patch.object(TestResultsFinisherTask, "hard_time_limit_task", 0)

    commit = CommitFactory.create(
        message="hello world",
        commitid="cd76b0821854a780b60012aed85af0a8263004ad",
        repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
        repository__owner__username="test-username",
        repository__owner__service="github",
        repository__name="test-repo-name",
    )
    commit.branch = "main"
    dbsession.add(commit)
    dbsession.flush()

    commit.repository.branch = "main"
    dbsession.flush()

    repoid = commit.repoid

    current_report_row = CommitReport(
        commit_id=commit.id_, report_type=ReportType.TEST_RESULTS.value
    )
    dbsession.add(current_report_row)
    dbsession.flush()

    pull = PullFactory.create(repository=commit.repository, head=commit.commitid)
    dbsession.add(pull)
    dbsession.flush()

    enriched_pull = EnrichedPull(
        database_pull=pull,
        provider_pull={},
    )

    _ = mocker.patch(
        "helpers.notifier.fetch_and_update_pull_request_information_from_commit",
        return_value=enriched_pull,
    )

    _ = mocker.patch(
        "tasks.test_results_finisher.fetch_and_update_pull_request_information_from_commit",
        return_value=enriched_pull,
    )

    uploads = [UploadFactory.create() for _ in range(4)]
    uploads[3].created_at += timedelta(0, 3)

    for i, upload in enumerate(uploads):
        upload.report = current_report_row
        upload.report.commit.repoid = repoid
        upload.build_url = f"https://example.com/build_url_{i}"
        dbsession.add(upload)
    dbsession.flush()

    flags = [RepositoryFlag(repository_id=repoid, flag_name=str(i)) for i in range(2)]
    for flag in flags:
        dbsession.add(flag)
    dbsession.flush()

    uploads[0].flags = [flags[0]]
    uploads[1].flags = [flags[1]]
    uploads[2].flags = []
    uploads[3].flags = [flags[0]]
    dbsession.flush()

    test_name = "test_name"
    test_suite = "test_testsuite"

    test_id1 = generate_test_id(repoid, test_name + "0", test_suite, "a")
    test1 = Test(
        id_=test_id1,
        repoid=repoid,
        name="Class Name\x1f" + test_name + "0",
        testsuite=test_suite,
        flags_hash="a",
    )
    dbsession.add(test1)

    test_id2 = generate_test_id(repoid, test_name + "1", test_suite, "b")
    test2 = Test(
        id_=test_id2,
        repoid=repoid,
        name=test_name + "1",
        testsuite=test_suite,
        flags_hash="b",
    )
    dbsession.add(test2)

    test_id3 = generate_test_id(repoid, test_name + "2", test_suite, "")
    test3 = Test(
        id_=test_id3,
        repoid=repoid,
        name="Other Class Name\x1f" + test_name + "2",
        testsuite=test_suite,
        flags_hash="",
    )
    dbsession.add(test3)

    test_id4 = generate_test_id(repoid, test_name + "3", test_suite, "")
    test4 = Test(
        id_=test_id4,
        repoid=repoid,
        name=test_name + "3",
        testsuite=test_suite,
        flags_hash="",
    )
    dbsession.add(test4)

    dbsession.flush()

    test_instances = [
        TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Failure),
            failure_message="This should not be in the comment, it will get overwritten by the last test instance",
            duration_seconds=1.0,
            upload_id=uploads[0].id,
        ),
        TestInstance(
            test_id=test_id2,
            outcome=str(Outcome.Failure),
            failure_message="Shared \n\n\n\n <pre> ````````\n \r\n\r\n | test | test | test </pre>failure message",
            duration_seconds=2.0,
            upload_id=uploads[1].id,
        ),
        TestInstance(
            test_id=test_id3,
            outcome=str(Outcome.Failure),
            failure_message="Shared \n\n\n\n <pre> \n  ````````  \n \r\n\r\n | test | test | test </pre>failure message",
            duration_seconds=3.0,
            upload_id=uploads[2].id,
        ),
        TestInstance(
            test_id=test_id1,
            outcome=str(Outcome.Failure),
            failure_message="<pre>Fourth \r\n\r\n</pre> | test  | instance |",
            duration_seconds=4.0,
            upload_id=uploads[3].id,
        ),
        TestInstance(
            test_id=test_id4,
            outcome=str(Outcome.Failure),
            failure_message=None,
            duration_seconds=5.0,
            upload_id=uploads[3].id,
        ),
    ]
    for instance in test_instances:
        dbsession.add(instance)
    dbsession.flush()

    return (repoid, commit, pull, test_instances)


@pytest.fixture
def test_results_setup_no_instances(mocker, dbsession):
    mocker.patch.object(TestResultsFinisherTask, "hard_time_limit_task", 0)

    commit = CommitFactory.create(
        message="hello world",
        commitid="cd76b0821854a780b60012aed85af0a8263004ad",
        repository__owner__unencrypted_oauth_token="test7lk5ndmtqzxlx06rip65nac9c7epqopclnoy",
        repository__owner__username="joseph-sentry",
        repository__owner__service="github",
        repository__name="codecov-demo",
    )
    commit.branch = "main"
    dbsession.add(commit)
    dbsession.flush()

    repoid = commit.repoid

    current_report_row = CommitReport(
        commit_id=commit.id_, report_type=ReportType.TEST_RESULTS.value
    )
    dbsession.add(current_report_row)
    dbsession.flush()

    pull = PullFactory.create(repository=commit.repository, head=commit.commitid)

    _ = mocker.patch(
        "helpers.notifier.fetch_and_update_pull_request_information_from_commit",
        return_value=EnrichedPull(
            database_pull=pull,
            provider_pull={},
        ),
    )

    uploads = [UploadFactory.create() for _ in range(4)]
    uploads[3].created_at += timedelta(0, 3)

    for upload in uploads:
        upload.report = current_report_row
        upload.report.commit.repoid = repoid
        dbsession.add(upload)
    dbsession.flush()

    flags = [RepositoryFlag(repository_id=repoid, flag_name=str(i)) for i in range(2)]
    for flag in flags:
        dbsession.add(flag)
    dbsession.flush()

    uploads[0].flags = [flags[0]]
    uploads[1].flags = [flags[1]]
    uploads[2].flags = []
    uploads[3].flags = [flags[0]]
    dbsession.flush()

    test_name = "test_name"
    test_suite = "test_testsuite"

    test_id1 = generate_test_id(repoid, test_name + "0", test_suite, "a")
    test1 = Test(
        id_=test_id1,
        repoid=repoid,
        name=test_name + "0",
        testsuite=test_suite,
        flags_hash="a",
    )
    dbsession.add(test1)

    test_id2 = generate_test_id(repoid, test_name + "1", test_suite, "b")
    test2 = Test(
        id_=test_id2,
        repoid=repoid,
        name=test_name + "1",
        testsuite=test_suite,
        flags_hash="b",
    )
    dbsession.add(test2)

    test_id3 = generate_test_id(repoid, test_name + "2", test_suite, "")
    test3 = Test(
        id_=test_id3,
        repoid=repoid,
        name=test_name + "2",
        testsuite=test_suite,
        flags_hash="",
    )
    dbsession.add(test3)

    test_id4 = generate_test_id(repoid, test_name + "3", test_suite, "")
    test4 = Test(
        id_=test_id4,
        repoid=repoid,
        name=test_name + "3",
        testsuite=test_suite,
        flags_hash="",
    )
    dbsession.add(test4)

    dbsession.flush()

    return (repoid, commit, pull, None)


class TestUploadTestFinisherTask(object):
    @pytest.mark.integration
    @pytest.mark.django_db(databases={"default"})
    def test_upload_finisher_task_call(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
    ):
        mock_feature = mocker.patch("services.test_results.FLAKY_TEST_DETECTION")
        mock_feature.check_value.return_value = False

        repoid, commit, pull, _ = test_results_setup

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": True}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
        )

        expected_result = {
            "notify_attempted": True,
            "notify_succeeded": True,
            QUEUE_NOTIFY_KEY: False,
        }

        test_results_mock_app.tasks[
            "app.tasks.cache_rollup.CacheTestRollupsTask"
        ].apply_async.assert_called_with(
            args=None,
            kwargs={
                "repoid": repoid,
                "branch": "main",
            },
        )

        assert expected_result == result
        mock_repo_provider_comments.post_comment.assert_called_with(
            pull.pullid,
            """### :x: 4 Tests Failed:
| Tests completed | Failed | Passed | Skipped |
|---|---|---|---|
| 4 | 4 | 0 | 0 |
<details><summary>View the top 3 failed tests by shortest run time</summary>

> 
> ```
> test_name1
> ```
> 
> <details><summary>Stack Traces | 2s run time</summary>
> 
> > `````````
> > Shared 
> > 
> > 
> > 
> >  <pre> ````````
> >  
> > 
> >  | test | test | test </pre>failure message
> > `````````
> > [View](https://example.com/build_url_1) the CI Build
> 
> </details>


> 
> ```
> Other Class Name test_name2
> ```
> 
> <details><summary>Stack Traces | 3s run time</summary>
> 
> > `````````
> > Shared 
> > 
> > 
> > 
> >  <pre> 
> >   ````````  
> >  
> > 
> >  | test | test | test </pre>failure message
> > `````````
> > [View](https://example.com/build_url_2) the CI Build
> 
> </details>


> 
> ```
> Class Name test_name0
> ```
> 
> <details><summary>Stack Traces | 4s run time</summary>
> 
> > 
> > ```
> > <pre>Fourth 
> > 
> > </pre> | test  | instance |
> > ```
> > 
> > [View](https://example.com/build_url_3) the CI Build
> 
> </details>

</details>

To view more test analytics, go to the [Test Analytics Dashboard](https://app.codecov.io/gh/test-username/test-repo-name/tests/main)
Got feedback? Let us know on [Github](https://github.com/codecov/feedback/issues)""",
        )

    @pytest.mark.integration
    def test_upload_finisher_task_call_no_failures(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
    ):
        mock_feature = mocker.patch("services.test_results.FLAKY_TEST_DETECTION")
        mock_feature.check_value.return_value = False

        repoid, commit, _, test_instances = test_results_setup

        for instance in test_instances:
            instance.outcome = str(Outcome.Pass)
        dbsession.flush()

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": True}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
        )

        expected_result = {
            "notify_attempted": False,
            "notify_succeeded": False,
            QUEUE_NOTIFY_KEY: True,
        }
        test_results_mock_app.tasks[
            "app.tasks.notify.Notify"
        ].apply_async.assert_called_with(
            args=None,
            kwargs={
                "commitid": commit.commitid,
                "current_yaml": {"codecov": {"max_report_age": False}},
                "repoid": repoid,
            },
        )

        test_results_mock_app.tasks[
            "app.tasks.cache_rollup.CacheTestRollupsTask"
        ].apply_async.assert_called_with(
            args=None,
            kwargs={
                "repoid": repoid,
                "branch": "main",
            },
        )

        assert expected_result == result

    @pytest.mark.integration
    def test_upload_finisher_task_call_no_success(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup_no_instances,
    ):
        mock_feature = mocker.patch("services.test_results.FLAKY_TEST_DETECTION")
        mock_feature.check_value.return_value = False

        repoid, commit, pull, _ = test_results_setup_no_instances

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": False}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
        )

        expected_result = {
            "notify_attempted": False,
            "notify_succeeded": False,
            QUEUE_NOTIFY_KEY: True,
        }

        assert expected_result == result

        mock_repo_provider_comments.post_comment.assert_called_with(
            pull.pullid,
            ":x: We are unable to process any of the uploaded JUnit XML files. Please ensure your files are in the right format.",
        )

        test_results_mock_app.tasks[
            "app.tasks.notify.Notify"
        ].apply_async.assert_called_with(
            args=None,
            kwargs={
                "commitid": commit.commitid,
                "current_yaml": {"codecov": {"max_report_age": False}},
                "repoid": repoid,
            },
        )

        test_results_mock_app.tasks[
            "app.tasks.cache_rollup.CacheTestRollupsTask"
        ].apply_async.assert_called_with(
            args=None,
            kwargs={
                "repoid": repoid,
                "branch": "main",
            },
        )

    @pytest.mark.integration
    def test_upload_finisher_task_call_upgrade_comment(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
    ):
        mock_feature = mocker.patch("services.test_results.FLAKY_TEST_DETECTION")
        mock_feature.check_value.return_value = False

        repoid, commit, pull, _ = test_results_setup

        repo = dbsession.query(Repository).filter(Repository.repoid == repoid).first()
        repo.owner.plan_activated_users = []
        repo.owner.plan = BillingPlan.pr_monthly.value
        repo.private = True
        dbsession.flush()

        pr_author = OwnerFactory(service="github", service_id=100)
        dbsession.add(pr_author)
        dbsession.flush()

        enriched_pull = EnrichedPull(
            database_pull=pull,
            provider_pull={"author": {"id": "100", "username": "test_username"}},
        )
        _ = mocker.patch(
            "helpers.notifier.fetch_and_update_pull_request_information_from_commit",
            return_value=enriched_pull,
        )
        _ = mocker.patch(
            "tasks.test_results_finisher.fetch_and_update_pull_request_information_from_commit",
            return_value=enriched_pull,
        )

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": True}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
        )

        expected_result = {
            "notify_attempted": False,
            "notify_succeeded": False,
            QUEUE_NOTIFY_KEY: False,
        }

        assert expected_result == result

        mock_repo_provider_comments.post_comment.assert_called_with(
            pull.pullid,
            f"The author of this PR, test_username, is not an activated member of this organization on Codecov.\nPlease [activate this user on Codecov]({get_members_url(pull)}) to display this PR comment.\nCoverage data is still being uploaded to Codecov.io for purposes of overall coverage calculations.\nPlease don't hesitate to email us at support@codecov.io with any questions.",
        )

        test_results_mock_app.tasks["app.tasks.notify.Notify"].assert_not_called()

        test_results_mock_app.tasks[
            "app.tasks.cache_rollup.CacheTestRollupsTask"
        ].apply_async.assert_called_with(
            args=None,
            kwargs={
                "repoid": repoid,
                "branch": "main",
            },
        )

    @pytest.mark.integration
    def test_upload_finisher_task_call_existing_comment(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
    ):
        mock_feature = mocker.patch("services.test_results.FLAKY_TEST_DETECTION")
        mock_feature.check_value.return_value = False

        repoid, commit, pull, _ = test_results_setup

        pull.commentid = 1
        dbsession.flush()

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": True}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
        )

        expected_result = {
            "notify_attempted": True,
            "notify_succeeded": True,
            QUEUE_NOTIFY_KEY: False,
        }

        test_results_mock_app.tasks[
            "app.tasks.cache_rollup.CacheTestRollupsTask"
        ].apply_async.assert_called_with(
            args=None,
            kwargs={
                "repoid": repoid,
                "branch": "main",
            },
        )

        mock_repo_provider_comments.edit_comment.assert_called_with(
            pull.pullid,
            1,
            """### :x: 4 Tests Failed:
| Tests completed | Failed | Passed | Skipped |
|---|---|---|---|
| 4 | 4 | 0 | 0 |
<details><summary>View the top 3 failed tests by shortest run time</summary>

> 
> ```
> test_name1
> ```
> 
> <details><summary>Stack Traces | 2s run time</summary>
> 
> > `````````
> > Shared 
> > 
> > 
> > 
> >  <pre> ````````
> >  
> > 
> >  | test | test | test </pre>failure message
> > `````````
> > [View](https://example.com/build_url_1) the CI Build
> 
> </details>


> 
> ```
> Other Class Name test_name2
> ```
> 
> <details><summary>Stack Traces | 3s run time</summary>
> 
> > `````````
> > Shared 
> > 
> > 
> > 
> >  <pre> 
> >   ````````  
> >  
> > 
> >  | test | test | test </pre>failure message
> > `````````
> > [View](https://example.com/build_url_2) the CI Build
> 
> </details>


> 
> ```
> Class Name test_name0
> ```
> 
> <details><summary>Stack Traces | 4s run time</summary>
> 
> > 
> > ```
> > <pre>Fourth 
> > 
> > </pre> | test  | instance |
> > ```
> > 
> > [View](https://example.com/build_url_3) the CI Build
> 
> </details>

</details>

To view more test analytics, go to the [Test Analytics Dashboard](https://app.codecov.io/gh/test-username/test-repo-name/tests/main)
Got feedback? Let us know on [Github](https://github.com/codecov/feedback/issues)""",
        )

        assert expected_result == result

    @pytest.mark.integration
    def test_upload_finisher_task_call_comment_fails(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
    ):
        mock_feature = mocker.patch("services.test_results.FLAKY_TEST_DETECTION")
        mock_feature.check_value.return_value = False

        repoid, commit, _, _ = test_results_setup

        mock_repo_provider_comments.post_comment.side_effect = TorngitClientError

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": True}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
        )

        expected_result = {
            "notify_attempted": True,
            "notify_succeeded": False,
            QUEUE_NOTIFY_KEY: False,
        }

        test_results_mock_app.tasks[
            "app.tasks.cache_rollup.CacheTestRollupsTask"
        ].apply_async.assert_called_with(
            args=None,
            kwargs={
                "repoid": repoid,
                "branch": "main",
            },
        )

        assert expected_result == result

    @pytest.mark.parametrize(
        "fail_count,count,recent_passes_count", [(2, 15, 13), (50, 150, 10)]
    )
    @pytest.mark.integration
    def test_upload_finisher_task_call_with_flaky(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
        fail_count,
        count,
        recent_passes_count,
    ):
        mock_feature = mocker.patch("services.test_results.FLAKY_TEST_DETECTION")
        mock_feature.check_value.return_value = True

        repoid, commit, pull, test_instances = test_results_setup

        for i, instance in enumerate(test_instances):
            if i != 2:
                dbsession.delete(instance)
        dbsession.flush()

        r = ReducedError()
        r.message = "failure_message"

        dbsession.add(r)
        dbsession.flush()

        f = Flake()
        f.repoid = repoid
        f.testid = test_instances[2].test_id
        f.reduced_error = r
        f.count = count
        f.fail_count = fail_count
        f.recent_passes_count = recent_passes_count
        f.start_date = datetime.now()
        f.end_date = None

        dbsession.add(f)
        dbsession.flush()

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": True}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={
                "codecov": {"max_report_age": False},
                "test_analytics": {"flake_detection": True},
            },
        )

        expected_result = {
            "notify_attempted": True,
            "notify_succeeded": True,
            "queue_notify": False,
        }

        assert expected_result == result

        test_results_mock_app.tasks[
            "app.tasks.cache_rollup.CacheTestRollupsTask"
        ].apply_async.assert_called_with(
            args=None,
            kwargs={
                "repoid": repoid,
                "branch": "main",
            },
        )

        mock_repo_provider_comments.post_comment.assert_called_with(
            pull.pullid,
            f"""### :x: 1 Tests Failed:
| Tests completed | Failed | Passed | Skipped |
|---|---|---|---|
| 1 | 1 | 0 | 0 |
<details><summary>{"View the top 1 failed tests by shortest run time" if (count - fail_count) == recent_passes_count else "View the full list of 1 :snowflake: flaky tests"}</summary>

> 
> ```
> Other Class Name test_name2
> ```
> {f"\n> **Flake rate in main:** 33.33% (Passed {count - fail_count} times, Failed {fail_count} times)" if (count - fail_count) != recent_passes_count else ""}
> <details><summary>Stack Traces | 3s run time</summary>
> 
> > `````````
> > Shared 
> > 
> > 
> > 
> >  <pre> 
> >   ````````  
> >  
> > 
> >  | test | test | test </pre>failure message
> > `````````
> > [View](https://example.com/build_url_2) the CI Build
> 
> </details>

</details>

To view more test analytics, go to the [Test Analytics Dashboard](https://app.codecov.io/gh/test-username/test-repo-name/tests/main)
Got feedback? Let us know on [Github](https://github.com/codecov/feedback/issues)""",
        )

    @pytest.mark.integration
    def test_upload_finisher_task_call_main_branch(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
    ):
        commit_yaml = {
            "codecov": {"max_report_age": False},
        }
        if flake_detection == "FLAKY_TEST_DETECTION":
            commit_yaml["test_analytics"] = {"flake_detection": True}
        elif flake_detection is None:
            commit_yaml["test_analytics"] = {"flake_detection": False}

        repoid, commit, pull, test_instances = test_results_setup

        commit.merged = True

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": True}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml=commit_yaml,
        )

        expected_result = {
            "notify_attempted": True,
            "notify_succeeded": True,
            "queue_notify": False,
        }

        assert expected_result == result

        if flake_detection is None:
            test_results_mock_app.tasks[
                "app.tasks.flakes.ProcessFlakesTask"
            ].apply_async.assert_not_called()
        else:
            test_results_mock_app.tasks[
                "app.tasks.flakes.ProcessFlakesTask"
            ].apply_async.assert_called_with(
                kwargs={
                    "repo_id": repoid,
                    "commit_id_list": [commit.commitid],
                    "branch": "main",
                },
            )
        test_results_mock_app.tasks[
            "app.tasks.cache_rollup.CacheTestRollupsTask"
        ].apply_async.assert_called_with(
            args=None,
            kwargs={
                "repoid": repoid,
                "branch": "main",
            },
        )

    @pytest.mark.integration
    @pytest.mark.django_db(databases={"default"})
    def test_upload_finisher_task_call_computed_name(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
    ):
        mock_feature = mocker.patch("services.test_results.FLAKY_TEST_DETECTION")
        mock_feature.check_value.return_value = False

        repoid, commit, pull, test_instances = test_results_setup

        for instance in test_instances:
            instance.test.computed_name = f"hello_{instance.test.name}"

        dbsession.flush()

        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": True}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml={"codecov": {"max_report_age": False}},
        )

        expected_result = {
            "notify_attempted": True,
            "notify_succeeded": True,
            QUEUE_NOTIFY_KEY: False,
        }

        assert expected_result == result
        mock_repo_provider_comments.post_comment.assert_called_with(
            pull.pullid,
            """### :x: 4 Tests Failed:
| Tests completed | Failed | Passed | Skipped |
|---|---|---|---|
| 4 | 4 | 0 | 0 |
<details><summary>View the top 3 failed tests by shortest run time</summary>

> 
> ```
> hello_test_name1
> ```
> 
> <details><summary>Stack Traces | 2s run time</summary>
> 
> > `````````
> > Shared 
> > 
> > 
> > 
> >  <pre> ````````
> >  
> > 
> >  | test | test | test </pre>failure message
> > `````````
> > [View](https://example.com/build_url_1) the CI Build
> 
> </details>


> 
> ```
> hello_Other Class Name test_name2
> ```
> 
> <details><summary>Stack Traces | 3s run time</summary>
> 
> > `````````
> > Shared 
> > 
> > 
> > 
> >  <pre> 
> >   ````````  
> >  
> > 
> >  | test | test | test </pre>failure message
> > `````````
> > [View](https://example.com/build_url_2) the CI Build
> 
> </details>


> 
> ```
> hello_Class Name test_name0
> ```
> 
> <details><summary>Stack Traces | 4s run time</summary>
> 
> > 
> > ```
> > <pre>Fourth 
> > 
> > </pre> | test  | instance |
> > ```
> > 
> > [View](https://example.com/build_url_3) the CI Build
> 
> </details>

</details>

To view more test analytics, go to the [Test Analytics Dashboard](https://app.codecov.io/gh/test-username/test-repo-name/tests/main)
Got feedback? Let us know on [Github](https://github.com/codecov/feedback/issues)""",
        )

    @pytest.mark.integration
    @pytest.mark.parametrize("plan", ["users-basic", "users-pr-inappm"])
    def test_upload_finisher_task_call_main_with_plan(
        self,
        mocker,
        mock_configuration,
        dbsession,
        codecov_vcr,
        mock_storage,
        mock_redis,
        celery_app,
        test_results_mock_app,
        mock_repo_provider_comments,
        test_results_setup,
        plan,
    ):
        mocked_get_flaky_tests = mocker.patch.object(
            TestResultsFinisherTask, "get_flaky_tests"
        )
        mock_feature = mocker.patch("services.test_results.FLAKY_TEST_DETECTION")
        mock_feature.check_value.return_value = True
        commit_yaml = {
            "codecov": {
                "max_report_age": False,
            },
            "test_analytics": {"flake_detection": True},
        }

        repoid, commit, pull, test_instances = test_results_setup

        commit.merged = True

        repo = dbsession.query(Repository).filter_by(repoid=repoid).first()
        repo.owner.plan = plan
        dbsession.flush()
        result = TestResultsFinisherTask().run_impl(
            dbsession,
            [
                [{"successful": True}],
            ],
            repoid=repoid,
            commitid=commit.commitid,
            commit_yaml=commit_yaml,
        )

        expected_result = {
            "notify_attempted": True,
            "notify_succeeded": True,
            "queue_notify": False,
        }

        assert expected_result == result

        test_results_mock_app.tasks[
            "app.tasks.flakes.ProcessFlakesTask"
        ].apply_async.assert_called_with(
            kwargs={
                "repo_id": repoid,
                "commit_id_list": [commit.commitid],
                "branch": "main",
            },
        )
