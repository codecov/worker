import logging

import httpx
from shared.config import get_config

from app import celery_app
from tasks.base import BaseCodecovTask

log = logging.getLogger(__name__)


class HTTPRequestTask(BaseCodecovTask, name="app.tasks.http_request.HTTPRequest"):
    """
    Task for making generic HTTP requests.
    """

    def run_impl(
        self,
        db_session,
        url,
        method="POST",
        headers=None,
        timeout=None,
        data=None,
        *args,
        **kwargs,
    ):
        if timeout is None:
            timeout = get_config("setup", "http", "timeouts", "external", default=10)

        params = dict(
            url=url,
            method=method,
            headers=headers,
            data=data,
            timeout=timeout,
        )

        log.info("HTTP request", extra=params)

        try:
            with httpx.Client() as client:
                res = client.request(**params)

            if res.status_code >= 500:
                # server error, we can retry later
                self._retry_task()

            if res.status_code >= 400:
                # malformed request, do not retry
                return {
                    "successful": False,
                    "status_code": res.status_code,
                    "response": res.text,
                }

            return {
                "successful": True,
                "status_code": res.status_code,
                "response": res.text,
            }
        except httpx.HTTPError:
            log.warning("HTTP request error", exc_info=True)
            self._retry_task()

    def _retry_task(self):
        # retry w/ exponential backoff
        self.retry(max_retries=5, countdown=20 * (2**self.request.retries))


RegisteredHTTPRequestTask = celery_app.register_task(HTTPRequestTask())
http_request_task = celery_app.tasks[RegisteredHTTPRequestTask.name]
