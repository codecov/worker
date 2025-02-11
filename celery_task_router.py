import shared.celery_config as shared_celery_config
from shared.celery_router import route_tasks_based_on_user_plan
from shared.plan.constants import DEFAULT_FREE_PLAN

from database.engine import get_db_session
from database.models.core import Commit, CompareCommit, Owner, Repository
from database.models.labelanalysis import LabelAnalysisRequest
from database.models.staticanalysis import StaticAnalysisSuite


def _get_user_plan_from_ownerid(db_session, ownerid, *args, **kwargs) -> str:
    result = db_session.query(Owner.plan).filter(Owner.ownerid == ownerid).first()
    if result:
        return result.plan
    return DEFAULT_FREE_PLAN


def _get_user_plan_from_repoid(db_session, repoid, *args, **kwargs) -> str:
    result = (
        db_session.query(Owner.plan)
        .join(Repository.owner)
        .filter(Repository.repoid == repoid)
        .first()
    )
    if result:
        return result.plan
    return DEFAULT_FREE_PLAN


def _get_user_plan_from_org_ownerid(dbsession, org_ownerid, *args, **kwargs) -> str:
    return _get_user_plan_from_ownerid(dbsession, ownerid=org_ownerid)


def _get_user_plan_from_comparison_id(dbsession, comparison_id, *args, **kwargs) -> str:
    result = (
        dbsession.query(Owner.plan)
        .join(CompareCommit.compare_commit)
        .join(Commit.repository)
        .join(Repository.owner)
        .filter(CompareCommit.id_ == comparison_id)
        .first()
    )
    if result:
        return result.plan
    return DEFAULT_FREE_PLAN


def _get_user_plan_from_label_request_id(dbsession, request_id, *args, **kwargs) -> str:
    result = (
        dbsession.query(Owner.plan)
        .join(LabelAnalysisRequest.head_commit)
        .join(Commit.repository)
        .join(Repository.owner)
        .filter(LabelAnalysisRequest.id_ == request_id)
        .first()
    )
    if result:
        return result.plan
    return DEFAULT_FREE_PLAN


def _get_user_plan_from_suite_id(dbsession, suite_id, *args, **kwargs) -> str:
    result = (
        dbsession.query(Owner.plan)
        .join(StaticAnalysisSuite.commit)
        .join(Commit.repository)
        .join(Repository.owner)
        .filter(StaticAnalysisSuite.id_ == suite_id)
        .first()
    )
    if result:
        return result.plan
    return DEFAULT_FREE_PLAN


def _get_user_plan_from_task(dbsession, task_name: str, task_kwargs: dict) -> str:
    owner_plan_lookup_funcs = {
        # from ownerid
        shared_celery_config.delete_owner_task_name: _get_user_plan_from_ownerid,
        shared_celery_config.send_email_task_name: _get_user_plan_from_ownerid,
        shared_celery_config.sync_repos_task_name: _get_user_plan_from_ownerid,
        shared_celery_config.sync_teams_task_name: _get_user_plan_from_ownerid,
        # from org_ownerid
        shared_celery_config.new_user_activated_task_name: _get_user_plan_from_org_ownerid,
        # from repoid
        shared_celery_config.pre_process_upload_task_name: _get_user_plan_from_repoid,
        shared_celery_config.upload_task_name: _get_user_plan_from_repoid,
        shared_celery_config.upload_processor_task_name: _get_user_plan_from_repoid,
        shared_celery_config.notify_task_name: _get_user_plan_from_repoid,
        shared_celery_config.commit_update_task_name: _get_user_plan_from_repoid,
        shared_celery_config.flush_repo_task_name: _get_user_plan_from_repoid,
        shared_celery_config.status_set_error_task_name: _get_user_plan_from_repoid,
        shared_celery_config.status_set_pending_task_name: _get_user_plan_from_repoid,
        shared_celery_config.pulls_task_name: _get_user_plan_from_repoid,
        shared_celery_config.upload_finisher_task_name: _get_user_plan_from_repoid,  # didn't want to directly import the task module
        shared_celery_config.manual_upload_completion_trigger_task_name: _get_user_plan_from_repoid,
        # from comparison_id
        shared_celery_config.compute_comparison_task_name: _get_user_plan_from_comparison_id,
        # from label_request_id
        shared_celery_config.label_analysis_task_name: _get_user_plan_from_label_request_id,
        # from suite_id
        shared_celery_config.static_analysis_task_name: _get_user_plan_from_suite_id,
    }
    func_to_use = owner_plan_lookup_funcs.get(
        task_name, lambda *args, **kwargs: DEFAULT_FREE_PLAN
    )
    return func_to_use(dbsession, **task_kwargs)


def route_task(name, args, kwargs, options, task=None, **kw):
    """Function to dynamically route tasks to the proper queue.
    Docs: https://docs.celeryq.dev/en/stable/userguide/routing.html#routers
    """

    user_plan = options.get("user_plan")
    if user_plan is None:
        db_session = get_db_session()
        user_plan = _get_user_plan_from_task(db_session, name, kwargs)
    return route_tasks_based_on_user_plan(name, user_plan)
