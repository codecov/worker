import logging
from datetime import datetime, timedelta
from typing import Iterator

from shared.celery_config import new_user_activated_task_name, notify_task_name
from sqlalchemy import func

from app import celery_app
from database.enums import Decoration
from database.models import Owner, Pull, Repository
from helpers.metrics import metrics
from shared.billing import is_pr_billing_plan
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class NewUserActivatedTask(BaseCodecovTask, name=new_user_activated_task_name):
    """
    This task resends notifications for pull requests that were authored by a newly activated
    user for an org that is on a PR-author billing plan ('users-pr-inapp*'). We do this so that
    pulls that received "ugprade" decoration will now be updated with the standard decoration.

    The steps are:
        - Ensure we are dealing with an activation for an org on a PR-author based plan
        - Get `pull` entries authored by the user that meet the following criteria:
            - Pull is for a repo owned by the provided `org_ownerid`
            - Pull is in the 'open' state
            - Pull was updated within the previous 10 days (Note: the `pull` table does NOT have
                a createstamp so we have to go by the updatestamp for now)
        - Schedule notify tasks to run again for the pulls that previously ran with just the
            "upgrade" decoration
    """

    def run_impl(self, db_session, org_ownerid, user_ownerid, *args, **kwargs):
        log.info(
            "New user activated",
            extra=dict(org_ownerid=org_ownerid, user_ownerid=user_ownerid),
        )
        pulls_notified = []

        if not self.is_org_on_pr_plan(db_session, org_ownerid):
            return {
                "notifies_scheduled": False,
                "pulls_notified": pulls_notified,
                "reason": "org not on pr author billing plan",
            }

        pulls = self.get_pulls_authored_by_user(db_session, org_ownerid, user_ownerid)

        # NOTE: we could also notify through pulls_sync task but we will notify directly here
        for pull in pulls:
            pull_commit_notifications = pull.get_head_commit_notifications()

            if not pull_commit_notifications:
                # don't know decoration type used so skip
                log.info(
                    "Skipping pull",
                    extra=dict(
                        org_ownerid=org_ownerid,
                        user_ownerid=user_ownerid,
                        repoid=pull.repoid,
                        pullid=pull.pullid,
                    ),
                )
                continue

            if self.possibly_resend_notifications(pull_commit_notifications, pull):
                pulls_notified.append(
                    dict(repoid=pull.repoid, pullid=pull.pullid, commitid=pull.head)
                )

        return {
            "notifies_scheduled": bool(len(pulls_notified)),
            "pulls_notified": pulls_notified,
            "reason": None
            if len(pulls_notified)
            else "no pulls/pull notifications met criteria",
        }

    def is_org_on_pr_plan(self, db_session, ownerid: int) -> bool:
        owner = db_session.query(Owner).filter(Owner.ownerid == ownerid).first()

        if not owner:
            log.info("Org not found", extra=dict(org_ownerid=ownerid))
            return False

        if owner.service == "gitlab" and owner.parent_service_id:
            # need to get root group so we can check plan info
            (gl_root_group,) = db_session.query(
                func.public.get_gitlab_root_group(ownerid)
            ).first()

            root_group = (
                db_session.query(Owner)
                .filter(Owner.ownerid == gl_root_group.get("ownerid"))
                .first()
            )
            return is_pr_billing_plan(root_group.plan)

        return is_pr_billing_plan(owner.plan)

    @metrics.timer("worker.task.new_user_activated.get_pulls_authored_by_user")
    def get_pulls_authored_by_user(
        self, db_session, org_ownerid: int, user_ownerid: int
    ) -> Iterator[Pull]:
        ten_days_ago = datetime.now() - timedelta(days=10)

        pulls = (
            db_session.query(Pull)
            .join(Pull.repository)
            .join(Repository.owner)
            .filter(
                Pull.updatestamp > ten_days_ago,
                Repository.ownerid == org_ownerid,
                Pull.author_id == user_ownerid,
                Pull.state == "open",
            )
            .all()
        )

        return pulls

    def possibly_resend_notifications(
        self, pull_commit_notifications, pull: Pull
    ) -> bool:
        was_notification_scheduled = False
        should_notify = any(
            commit_notification.decoration_type == Decoration.upgrade
            for commit_notification in pull_commit_notifications
        )

        if should_notify:
            repoid = pull.repoid
            pullid = pull.pullid
            commitid = pull.head
            log.info(
                "Scheduling notify task",
                extra=dict(repoid=repoid, pullid=pullid, commitid=pull.head),
            )
            self.app.tasks[notify_task_name].apply_async(
                kwargs=dict(repoid=repoid, commitid=pull.head)
            )
            was_notification_scheduled = True

        return was_notification_scheduled


RegisteredNewUserActivatedTask = celery_app.register_task(NewUserActivatedTask())
new_user_activated_task = celery_app.tasks[NewUserActivatedTask.name]
