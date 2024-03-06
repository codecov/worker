import json

import pytest
from celery.exceptions import Retry

from tasks.http_request import HTTPRequestTask


@pytest.mark.integration
class TestHTTPRequestTask:
    def test_http_request_run_async_200(self, dbsession, codecov_vcr):
        task = HTTPRequestTask()
        res = task.run_impl(
            dbsession,
            url="http://mockbin.org/bin/a1316495-ee65-4eab-b8e3-d5cb7cfc7519?foo=bar&foo=baz",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Codecov",
            },
            data=json.dumps({"testing": 123}),
        )
        assert res == {"response": "ok", "status_code": 200, "successful": True}

    def test_http_request_run_async_400(self, dbsession, codecov_vcr):
        task = HTTPRequestTask()
        res = task.run_impl(
            dbsession,
            url="http://mockbin.org/bin/e4e9db83-b7b9-4a50-b929-d672bcc8d075?foo=bar&foo=baz",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Codecov",
            },
            data=json.dumps({"testing": 123}),
        )
        assert res == {
            "response": "bad request",
            "status_code": 400,
            "successful": False,
        }

    def test_http_request_run_async_500(self, dbsession, codecov_vcr):
        task = HTTPRequestTask()
        with pytest.raises(Retry):
            task.run_impl(
                dbsession,
                url="http://mockbin.org/bin/c0052243-3391-4a30-bed7-066e4cd04074?foo=bar&foo=baz",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Codecov",
                },
                data=json.dumps({"testing": 123}),
            )

    def test_http_request_run_async_connection_error(self, dbsession, codecov_vcr):
        task = HTTPRequestTask()
        with pytest.raises(Retry):
            task.run_impl(
                dbsession,
                url="http://probablynotavaliddomain.com",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Codecov",
                },
                data=json.dumps({"testing": 123}),
            )
