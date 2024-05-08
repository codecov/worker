import logging

from sqlalchemy import desc

from app import celery_app
from celery_config import update_branches_task_name
from database.models.core import Branch, Commit
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class UpdateBranchesTask(BaseCodecovTask, name=update_branches_task_name):
    def run_impl(
        self,
        db_session,
        *args,
        branch_name=None,
        incorrect_commitid=None,
        dry_run=True,
        **kwargs,
    ):
        if branch_name is None:
            log.warning("No branch name specified, not updating any branches")
            return {"attempted": False}

        log.info(
            "Doing update branches for branch",
            extra=dict(branch_name=branch_name, incorrect_commitid=incorrect_commitid),
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
            for i in range(0, len(branches_to_update), chunk_size)
        ]

        for chunk in chunks:
            relevant_repos = [branch.repoid for branch in chunk]
            # query similar to what we do to fetch the latest test instances
            # this time there is no need to join
            # this will fetch the commits in all the repos and group them together
            # and order them by timestamp descending
            # then only select one commit per repo starting with the first one
            # it sees, thus it will select the latest commit for that repo
            relevant_commits = (
                db_session.query(Commit)
                .filter(
                    Commit.branch == branch_name,
                    Commit.repoid.in_(relevant_repos),
                )
                .order_by(Commit.repoid)
                .order_by(desc(Commit.timestamp))
                .distinct(Commit.repoid)
                .all()
            )
            commit_dict = {commit.repoid: commit for commit in relevant_commits}
            for branch in chunk:
                log.info(
                    "Updating branch on repo",
                    extra=dict(
                        branch_name=branch_name,
                        repoid=branch.repoid,
                        incorrect_commitid=incorrect_commitid,
                    ),
                )

                latest_commit_on_branch = commit_dict.get(branch.repoid, None)
                if latest_commit_on_branch is None:
                    log.info(
                        "No existing commits on this branch in this repo",
                        extra=dict(
                            branch_name=branch_name,
                            repoid=branch.repoid,
                            incorrect_commitid=incorrect_commitid,
                        ),
                    )
                    continue

                new_branch_head = latest_commit_on_branch.commitid
                log.info(
                    "Found latest commit on branch and updating branch head to",
                    extra=dict(
                        branch_name=branch_name,
                        repoid=branch.repoid,
                        latest_commit=new_branch_head,
                        incorrect_commitid=incorrect_commitid,
                    ),
                )

                if not dry_run:
                    branch.head = new_branch_head

            if not dry_run:
                log.info(
                    "flushing and commiting changes to chunk",
                    extra=dict(
                        branch_name=branch_name, incorrect_commitid=incorrect_commitid
                    ),
                )
                db_session.commit()

        return {"successful": True}


RegisteredTrialExpirationCronTask = celery_app.register_task(UpdateBranchesTask())
update_branches_task = celery_app.tasks[UpdateBranchesTask.name]
