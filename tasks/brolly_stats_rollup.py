import datetime
import json
import logging

import httpx
from shared.celery_config import brolly_stats_rollup_task_name
from shared.config import get_config

from app import celery_app
from database.models import Commit, Constants, Repository, Upload, User
from tasks.crontasks import CodecovCronTask

log = logging.getLogger(__name__)

DEFAULT_BROLLY_ENDPOINT = "https://codecov.io/self-hosted/telemetry"


class BrollyStatsRollupTask(CodecovCronTask, name=brolly_stats_rollup_task_name):
    """
    By default, this cron task collects anonymous statistics about the Codecov instance
    and submits them to Codecov to give us insight into the size of our self-hosted,
    open-source userbase.

    Installations can configure the behavior in `codecov.yml`:
    - `setup.telemetry.enabled` (default True): Control whether stats are collected at all.
    - `setup.telemetry.endpoint_override`: Control where stats are sent.
    - `setup.telemetry.anonymous` (default True): Request that brolly not save identifiable
      information such as the IP address of the installation that submitted the stats.
    - `setup.telemetry.admin_email`: Contact information for the installation owner.
    """

    @classmethod
    def get_min_seconds_interval_between_executions(cls):
        return 72000  # 20h

    def _get_install_id(self, db_session):
        """
        Anonymous, randomly-generated UUID created during DB setup.
        """
        return db_session.query(Constants).get("install_id").value

    def _get_users_count(self, db_session):
        return db_session.query(User.id_).count()

    def _get_repos_count(self, db_session):
        return db_session.query(Repository.repoid).count()

    def _get_commits_count(self, db_session):
        return db_session.query(Commit.id_).count()

    def _get_uploads_count_last_24h(self, db_session):
        time_24h_ago = datetime.datetime.now() - datetime.timedelta(days=1)
        return db_session.query(Upload).filter(Upload.created_at > time_24h_ago).count()

    def _get_anonymous(self):
        """
        If this is true, brolly will refrain from logging things like the IP address used to
        submit the stats.
        """
        return get_config("setup", "telemetry", "anonymous", default=True)

    def _get_version(self, db_session):
        return db_session.query(Constants).get("version").value

    def _get_endpoint_url(self):
        """
        Where to send stats.
        """
        return get_config(
            "setup", "telemetry", "endpoint_override", default=DEFAULT_BROLLY_ENDPOINT
        )

    def _get_admin_email(self):
        """
        Contact information for the owner of the installation.
        If not populated, it will be omitted from the payload.
        """
        return get_config("setup", "telemetry", "admin_email", default=None)

    def run_cron_task(self, db_session, *args, **kwargs):
        # We shouldn't even schedule this task if it's not enabled, but
        # let's double-check that we're supposed to collect stats.
        if not get_config("setup", "telemetry", "enabled", default=True):
            return dict(uploaded=False, reason="telemetry disabled in codecov.yml")

        payload = dict(
            install_id=self._get_install_id(db_session),
            users=self._get_users_count(db_session),
            repos=self._get_repos_count(db_session),
            commits=self._get_commits_count(db_session),
            uploads_24h=self._get_uploads_count_last_24h(db_session),
            version=self._get_version(db_session),
            anonymous=self._get_anonymous(),
        )

        admin_email = self._get_admin_email()
        if admin_email:
            payload["admin_email"] = admin_email

        # Perform the upload
        brolly_endpoint = self._get_endpoint_url()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        res = httpx.Client().post(
            url=brolly_endpoint,
            content=json.dumps(payload),
            headers=headers,
        )

        match res.status_code:
            case httpx.codes.OK:
                log.info(
                    "Successfully uploaded stats to brolly", extra=dict(response=res)
                )
            case _:
                log.error("Failed to upload stats to brolly", extra=dict(response=res))
                return dict(uploaded=False, payload=payload)

        return dict(uploaded=True, payload=payload)


RegisteredBrollyStatsRollupTask = celery_app.register_task(BrollyStatsRollupTask())
brolly_stats_rollup_task = celery_app.tasks[RegisteredBrollyStatsRollupTask.name]
