import pytest
import shared.celery_config as shared_celery_config
from shared.plan.constants import DEFAULT_FREE_PLAN, PlanName

from celery_task_router import (
    _get_user_plan_from_comparison_id,
    _get_user_plan_from_label_request_id,
    _get_user_plan_from_org_ownerid,
    _get_user_plan_from_ownerid,
    _get_user_plan_from_profiling_commit,
    _get_user_plan_from_profiling_upload,
    _get_user_plan_from_repoid,
    _get_user_plan_from_suite_id,
    _get_user_plan_from_task,
    route_task,
)
from database.tests.factories.core import (
    CommitFactory,
    CompareCommitFactory,
    OwnerFactory,
    RepositoryFactory,
)
from database.tests.factories.labelanalysis import LabelAnalysisRequestFactory
from database.tests.factories.profiling import (
    ProfilingCommitFactory,
    ProfilingUploadFactory,
)
from database.tests.factories.staticanalysis import StaticAnalysisSuiteFactory


@pytest.fixture
def fake_owners(dbsession):
    owner = OwnerFactory.create(plan=PlanName.CODECOV_PRO_MONTHLY.value)
    owner_enterprise_cloud = OwnerFactory.create(
        plan=PlanName.ENTERPRISE_CLOUD_YEARLY.value
    )
    dbsession.add(owner)
    dbsession.add(owner_enterprise_cloud)
    dbsession.flush()
    return (owner, owner_enterprise_cloud)


@pytest.fixture
def fake_repos(dbsession, fake_owners):
    (owner, owner_enterprise_cloud) = fake_owners
    repo = RepositoryFactory.create(owner=owner)
    repo_enterprise_cloud = RepositoryFactory.create(owner=owner_enterprise_cloud)
    dbsession.add(repo)
    dbsession.add(repo_enterprise_cloud)
    dbsession.flush()
    return (repo, repo_enterprise_cloud)


@pytest.fixture
def fake_profiling_commit(dbsession, fake_repos):
    (repo, repo_enterprise_cloud) = fake_repos
    profiling_commit = ProfilingCommitFactory.create(repository=repo)
    profiling_commit_enterprise = ProfilingCommitFactory.create(
        repository=repo_enterprise_cloud
    )
    dbsession.add(profiling_commit)
    dbsession.add(profiling_commit_enterprise)
    dbsession.flush()
    return (profiling_commit, profiling_commit_enterprise)


@pytest.fixture
def fake_profiling_commit_upload(dbsession, fake_profiling_commit):
    (profiling_commit, profiling_commit_enterprise) = fake_profiling_commit

    profiling_upload = ProfilingUploadFactory(profiling_commit=profiling_commit)
    profiling_upload_enterprise = ProfilingUploadFactory(
        profiling_commit=profiling_commit_enterprise
    )
    dbsession.add(profiling_upload)
    dbsession.add(profiling_upload_enterprise)
    dbsession.flush()
    return (profiling_upload, profiling_upload_enterprise)


@pytest.fixture
def fake_comparison_commit(dbsession, fake_repos):
    (repo, repo_enterprise_cloud) = fake_repos

    commmit = CommitFactory.create(repository=repo)
    commmit_enterprise = CommitFactory.create(repository=repo_enterprise_cloud)
    dbsession.add(commmit)
    dbsession.add(commmit_enterprise)
    dbsession.flush()
    compare_commit = CompareCommitFactory(compare_commit=commmit)
    compare_commit_enterprise = CompareCommitFactory(compare_commit=commmit_enterprise)
    dbsession.add(compare_commit)
    dbsession.add(compare_commit_enterprise)
    dbsession.flush()
    return (compare_commit, compare_commit_enterprise)


@pytest.fixture
def fake_label_analysis_request(dbsession, fake_repos):
    (repo, repo_enterprise_cloud) = fake_repos

    commmit = CommitFactory.create(repository=repo)
    commmit_enterprise = CommitFactory.create(repository=repo_enterprise_cloud)
    dbsession.add(commmit)
    dbsession.add(commmit_enterprise)
    dbsession.flush()
    label_analysis_request = LabelAnalysisRequestFactory(head_commit=commmit)
    label_analysis_request_enterprise = LabelAnalysisRequestFactory(
        head_commit=commmit_enterprise
    )
    dbsession.add(label_analysis_request)
    dbsession.add(label_analysis_request_enterprise)
    dbsession.flush()
    return (label_analysis_request, label_analysis_request_enterprise)


@pytest.fixture
def fake_static_analysis_suite(dbsession, fake_repos):
    (repo, repo_enterprise_cloud) = fake_repos

    commmit = CommitFactory.create(repository=repo)
    commmit_enterprise = CommitFactory.create(repository=repo_enterprise_cloud)
    dbsession.add(commmit)
    dbsession.add(commmit_enterprise)
    dbsession.flush()
    static_analysis_suite = StaticAnalysisSuiteFactory(commit=commmit)
    static_analysis_suite_enterprise = StaticAnalysisSuiteFactory(
        commit=commmit_enterprise
    )
    dbsession.add(static_analysis_suite)
    dbsession.add(static_analysis_suite_enterprise)
    dbsession.flush()
    return (static_analysis_suite, static_analysis_suite_enterprise)


def test_get_owner_plan_from_id(dbsession, fake_owners):
    (owner, owner_enterprise_cloud) = fake_owners
    assert (
        _get_user_plan_from_ownerid(dbsession, owner.ownerid)
        == PlanName.CODECOV_PRO_MONTHLY.value
    )
    assert (
        _get_user_plan_from_ownerid(dbsession, owner_enterprise_cloud.ownerid)
        == PlanName.ENTERPRISE_CLOUD_YEARLY.value
    )
    assert _get_user_plan_from_ownerid(dbsession, 10000000) == DEFAULT_FREE_PLAN


def test_get_user_plan_from_org_ownerid(dbsession, fake_owners):
    (owner, owner_enterprise_cloud) = fake_owners
    assert (
        _get_user_plan_from_org_ownerid(dbsession, owner.ownerid)
        == PlanName.CODECOV_PRO_MONTHLY.value
    )
    assert (
        _get_user_plan_from_org_ownerid(dbsession, owner_enterprise_cloud.ownerid)
        == PlanName.ENTERPRISE_CLOUD_YEARLY.value
    )


def test_get_owner_plan_from_repoid(dbsession, fake_repos):
    (repo, repo_enterprise_cloud) = fake_repos
    assert (
        _get_user_plan_from_repoid(dbsession, repo.repoid)
        == PlanName.CODECOV_PRO_MONTHLY.value
    )
    assert (
        _get_user_plan_from_repoid(dbsession, repo_enterprise_cloud.repoid)
        == PlanName.ENTERPRISE_CLOUD_YEARLY.value
    )
    assert _get_user_plan_from_repoid(dbsession, 10000000) == DEFAULT_FREE_PLAN


def test_get_user_plan_from_profiling_commit(dbsession, fake_profiling_commit):
    (profiling_commit, profiling_commit_enterprise) = fake_profiling_commit
    assert (
        _get_user_plan_from_profiling_commit(dbsession, profiling_commit.id)
        == PlanName.CODECOV_PRO_MONTHLY.value
    )
    assert (
        _get_user_plan_from_profiling_commit(dbsession, profiling_commit_enterprise.id)
        == PlanName.ENTERPRISE_CLOUD_YEARLY.value
    )
    assert (
        _get_user_plan_from_profiling_commit(dbsession, 10000000) == DEFAULT_FREE_PLAN
    )


def test_get_user_plan_from_profiling_upload(dbsession, fake_profiling_commit_upload):
    (profiling_upload, profiling_upload_enterprise) = fake_profiling_commit_upload
    assert (
        _get_user_plan_from_profiling_upload(dbsession, profiling_upload.id)
        == PlanName.CODECOV_PRO_MONTHLY.value
    )
    assert (
        _get_user_plan_from_profiling_upload(dbsession, profiling_upload_enterprise.id)
        == PlanName.ENTERPRISE_CLOUD_YEARLY.value
    )
    assert (
        _get_user_plan_from_profiling_upload(dbsession, 10000000) == DEFAULT_FREE_PLAN
    )


def test_get_user_plan_from_comparison_id(dbsession, fake_comparison_commit):
    (compare_commit, compare_commit_enterprise) = fake_comparison_commit
    assert (
        _get_user_plan_from_comparison_id(dbsession, comparison_id=compare_commit.id)
        == PlanName.CODECOV_PRO_MONTHLY.value
    )
    assert (
        _get_user_plan_from_comparison_id(
            dbsession, comparison_id=compare_commit_enterprise.id
        )
        == PlanName.ENTERPRISE_CLOUD_YEARLY.value
    )
    assert _get_user_plan_from_comparison_id(dbsession, 10000000) == DEFAULT_FREE_PLAN


def test_get_user_plan_from_label_request_id(dbsession, fake_label_analysis_request):
    (
        label_analysis_request,
        label_analysis_request_enterprise,
    ) = fake_label_analysis_request
    assert (
        _get_user_plan_from_label_request_id(
            dbsession, request_id=label_analysis_request.id
        )
        == PlanName.CODECOV_PRO_MONTHLY.value
    )
    assert (
        _get_user_plan_from_label_request_id(
            dbsession, request_id=label_analysis_request_enterprise.id
        )
        == PlanName.ENTERPRISE_CLOUD_YEARLY.value
    )
    assert (
        _get_user_plan_from_label_request_id(dbsession, 10000000) == DEFAULT_FREE_PLAN
    )


def test_get_user_plan_from_static_analysis_suite(
    dbsession, fake_static_analysis_suite
):
    (
        static_analysis_suite,
        static_analysis_suite_enterprise,
    ) = fake_static_analysis_suite
    assert (
        _get_user_plan_from_suite_id(dbsession, suite_id=static_analysis_suite.id)
        == PlanName.CODECOV_PRO_MONTHLY.value
    )
    assert (
        _get_user_plan_from_suite_id(
            dbsession, suite_id=static_analysis_suite_enterprise.id
        )
        == PlanName.ENTERPRISE_CLOUD_YEARLY.value
    )
    assert _get_user_plan_from_suite_id(dbsession, 10000000) == DEFAULT_FREE_PLAN


def test_get_user_plan_from_task(
    dbsession,
    fake_repos,
    fake_profiling_commit,
    fake_profiling_commit_upload,
    fake_comparison_commit,
):
    (repo, repo_enterprise_cloud) = fake_repos
    profiling_commit = fake_profiling_commit[0]
    profiling_upload = fake_profiling_commit_upload[0]
    compare_commit = fake_comparison_commit[0]
    task_kwargs = dict(repoid=repo.repoid, commitid=0, debug=False, rebuild=False)
    assert (
        _get_user_plan_from_task(
            dbsession, shared_celery_config.upload_task_name, task_kwargs
        )
        == PlanName.CODECOV_PRO_MONTHLY.value
    )

    task_kwargs = dict(
        repoid=repo_enterprise_cloud.repoid, commitid=0, debug=False, rebuild=False
    )
    assert (
        _get_user_plan_from_task(
            dbsession, shared_celery_config.upload_task_name, task_kwargs
        )
        == PlanName.ENTERPRISE_CLOUD_YEARLY.value
    )

    task_kwargs = dict(ownerid=repo.ownerid)
    assert (
        _get_user_plan_from_task(
            dbsession, shared_celery_config.delete_owner_task_name, task_kwargs
        )
        == PlanName.CODECOV_PRO_MONTHLY.value
    )

    task_kwargs = dict(org_ownerid=repo.ownerid, user_ownerid=20)
    assert (
        _get_user_plan_from_task(
            dbsession, shared_celery_config.new_user_activated_task_name, task_kwargs
        )
        == PlanName.CODECOV_PRO_MONTHLY.value
    )

    task_kwargs = dict(profiling_id=profiling_commit.id)
    assert (
        _get_user_plan_from_task(
            dbsession, shared_celery_config.profiling_collection_task_name, task_kwargs
        )
        == PlanName.CODECOV_PRO_MONTHLY.value
    )

    task_kwargs = dict(profiling_upload_id=profiling_upload.id)
    assert (
        _get_user_plan_from_task(
            dbsession,
            shared_celery_config.profiling_normalization_task_name,
            task_kwargs,
        )
        == PlanName.CODECOV_PRO_MONTHLY.value
    )

    task_kwargs = dict(comparison_id=compare_commit.id)
    assert (
        _get_user_plan_from_task(
            dbsession, shared_celery_config.compute_comparison_task_name, task_kwargs
        )
        == PlanName.CODECOV_PRO_MONTHLY.value
    )

    task_kwargs = dict(
        repoid=repo_enterprise_cloud.repoid, commitid=0, debug=False, rebuild=False
    )
    assert (
        _get_user_plan_from_task(dbsession, "unknown task", task_kwargs)
        == DEFAULT_FREE_PLAN
    )


def test_route_task(mocker, dbsession, fake_repos):
    mock_get_db_session = mocker.patch("celery_task_router.get_db_session")
    mock_route_tasks_shared = mocker.patch(
        "celery_task_router.route_tasks_based_on_user_plan"
    )
    mock_get_db_session.return_value = dbsession
    mock_route_tasks_shared.return_value = {"queue": "correct queue"}
    repo = fake_repos[0]
    task_kwargs = dict(repoid=repo.repoid, commitid=0, debug=False, rebuild=False)
    response = route_task(shared_celery_config.upload_task_name, [], task_kwargs, {})
    assert response == {"queue": "correct queue"}
    mock_get_db_session.assert_called()
    mock_route_tasks_shared.assert_called_with(
        shared_celery_config.upload_task_name, PlanName.CODECOV_PRO_MONTHLY.value
    )
