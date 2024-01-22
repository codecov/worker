import logging

from app import celery_app
from celery_config import update_branches_task_name
from database.models.core import Branch, Commit, Repository
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class UpdateBranchesTask(BaseCodecovTask, name=update_branches_task_name):
    async def run_async(
        self, db_session, *args, branch_name=None, ownerid=None, dry_run=True, **kwargs
    ):
        if branch_name is None:
            log.warning("No branch name specified, not updating any branches")
            return {"attempted": False}

        log.info(
            "Doing update branches for branch",
            extra=dict(branch_name=branch_name, ownerid=ownerid),
        )
        if ownerid is not None:
            log.info(
                "Owner id was specified, only updating branches in the repo of that owner",
                extra=dict(branch_name=branch_name, ownerid=ownerid),
            )
            repoids = (
                db_session.query(Repository.repoid)
                .filter(Repository.ownerid == ownerid)
                .all()
            )
            log.info(
                "repo ids we're taking a look at",
                extra=dict(repoids=repoids, branch_name=branch_name, ownerid=ownerid),
            )
            query = (
                db_session.query(Branch)
                .filter(Branch.branch == branch_name, Branch.repoid.in_(repoids))
                .yield_per(10)
            )
        else:
            log.info(
                "No owner id specified updating for branches in all orgs' repos",
                extra=dict(branch_name=branch_name, ownerid=ownerid),
            )
            query = (
                db_session.query(Branch)
                .filter(
                    Branch.branch == branch_name,
                )
                .yield_per(10)
            )

        for branch in query:
            log.info(
                "Updating branch on repo",
                extra=dict(branch_name=branch_name, repoid=branch.repoid),
            )
            existing_commit = (
                db_session.query(Commit)
                .filter(Commit.repoid == branch.repoid, Commit.commitid == branch.head)
                .first()
            )
            if existing_commit is not None:
                log.info(
                    "Existing commit in the repo already exists, no need to update",
                    extra=dict(
                        branch_name=branch_name,
                        repoid=branch.repoid,
                        existing_commit=existing_commit.commitid,
                    ),
                )
                continue

            log.info(
                "No existing commit checking latest commit on branch in repo",
                extra=dict(branch_name=branch_name, repoid=branch.repoid),
            )

            latest_commit_on_branch = (
                db_session.query(Commit)
                .filter(
                    Commit.branch == branch_name,
                    Commit.repoid == branch.repoid,
                )
                .order_by(Commit.updatestamp.desc())
                .first()
            )
            if latest_commit_on_branch is None:
                log.info(
                    "No existing commits on this branch in this repo",
                    extra=dict(branch_name=branch_name, repoid=branch.repoid),
                )
                continue

            new_branch_head = latest_commit_on_branch.commitid
            log.info(
                "Found latest commit on branch and updating branch head to",
                extra=dict(
                    branch_name=branch_name,
                    repoid=branch.repoid,
                    latest_commit=new_branch_head,
                ),
            )

            if not dry_run:
                branch.head = new_branch_head
                db_session.flush()

        return {"successful": True}


RegisteredTrialExpirationCronTask = celery_app.register_task(UpdateBranchesTask())
update_branches_task = celery_app.tasks[UpdateBranchesTask.name]
