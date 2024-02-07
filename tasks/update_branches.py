import logging

from app import celery_app
from celery_config import update_branches_task_name
from database.models.core import Branch, Commit, Repository
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class UpdateBranchesTask(BaseCodecovTask, name=update_branches_task_name):
    async def run_async(
        self,
        db_session,
        *args,
        branch_name=None,
        incorrect_commitid=None,
        dry_run=True,
        **kwargs
    ):
        if branch_name is None:
            log.warning("No branch name specified, not updating any branches")
            return {"attempted": False}

        log.info(
            "Doing update branches for branch",
            extra=dict(branch_name=branch_name),
        )

        branches_to_update = (
            db_session.query(Branch)
            .filter(
                Branch.branch == branch_name,
                Branch.head == incorrect_commitid,
            )
            .all()
        )

        chunk_size = 1000
        chunks = [
            branches_to_update[i : i + chunk_size]
            for i in range(len(branches_to_update), chunk_size)
        ]

        for chunk in chunks:
            for branch in chunk:
                log.info(
                    "Updating branch on repo",
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

            if not dry_run:
                log.info("flushing and commiting changes to chunk")
                db_session.commit()

        return {"successful": True}


RegisteredTrialExpirationCronTask = celery_app.register_task(UpdateBranchesTask())
update_branches_task = celery_app.tasks[UpdateBranchesTask.name]
