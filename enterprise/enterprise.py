# -*- coding: utf-8 -*-
import logging
import app
import argparse
import os

from services.storage import get_storage_client
from shared.config import get_config
from helpers.version import get_current_version
from shared.storage.exceptions import BucketAlreadyExistsError

log = logging.getLogger(__name__)

initialization_text = """
  _____          _
 / ____|        | |
| |     ___   __| | ___  ___ _____   __
| |    / _ \\ / _` |/ _ \\/ __/ _ \\ \\ / /
| |___| (_) | (_| |  __/ (_| (_) \\ V /
 \\_____\\___/ \\__,_|\\___|\\___\\___/ \\_/
                              {version}

"""


def deal_test_command(parser, codecov_args):
    parser.error("System not suitable to run TEST mode")


def deal_web_command(parser, codecov):
    parser.error("System not suitable to run WEB mode")


def setup_worker():
    print(initialization_text.format(version=get_current_version()))
    storage_client = get_storage_client()
    minio_config = get_config('services', 'minio')
    bucket_name = get_config("services", "minio", "bucket", default="archive")
    region = minio_config.get('region', 'us-east-1')
    try:
        storage_client.create_root_storage(bucket_name, region)
        log.info("Initializing bucket %s", bucket_name)
    except BucketAlreadyExistsError:
        pass


def deal_worker_command(parser, codecov):
    setup_worker()
    return app.celery_app.worker_main(
        argv=[
            "worker",
            "-n",
            codecov.name,
            "-c",
            codecov.concurrency,
            "-l",
            ("debug" if codecov.debug else "info"),
            "-Q",
            codecov.queue,
        ]
    )


def get_arg_parser():
    parser = argparse.ArgumentParser(
        prog="codecov",
        add_help=True,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Read more at https://github.com/codecov/enterprise""",
    )
    subparsers = parser.add_subparsers(title="Commands")

    cmd_web = subparsers.add_parser("web")
    cmd_web.set_defaults(proc="web", func=deal_web_command)

    cmd_worker = subparsers.add_parser("worker")
    cmd_worker.set_defaults(
        proc="worker",
        func=deal_worker_command,
        help="Run the celery worker. Take same arguments as 'celery worker'.",
    )
    cmd_worker.add_argument(
        "-c",
        "--concurrency",
        nargs="?",
        default="2",
        help="number or celery concurrency",
    )
    cmd_worker.add_argument(
        "-n",
        "--name",
        dest="name",
        nargs="?",
        default=os.getenv("HOSTNAME", "worker"),
        help="node name",
    )
    cmd_worker.add_argument(
        "-q",
        "--queue",
        nargs="?",
        default="celery",
        help="queues to listen to for this worker",
    )
    cmd_worker.add_argument(
        "--debug", action="store_true", default=False, help="enable celery debug mode"
    )

    cmd_test = subparsers.add_parser("test", help="Run tests on service integrations")
    cmd_test.set_defaults(proc="test", func=deal_test_command)
    return parser


def main():
    parser = get_arg_parser()
    codecov, unknown = parser.parse_known_args()
    return codecov.func(parser, codecov)


if __name__ == "__main__":
    main()
