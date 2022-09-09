# -*- coding: utf-8 -*-
import logging
import typing

import click
from shared.config import get_config
from shared.storage.exceptions import BucketAlreadyExistsError

import app
from helpers.version import get_current_version
from services.storage import get_storage_client

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


@click.group()
@click.pass_context
def cli(ctx: click.Context):
    pass


@cli.command()
def test():
    raise click.ClickException("System not suitable to run TEST mode")


@cli.command()
def web():
    raise click.ClickException("System not suitable to run WEB mode")


def setup_worker():
    print(initialization_text.format(version=get_current_version()))
    storage_client = get_storage_client()
    minio_config = get_config("services", "minio")
    bucket_name = get_config("services", "minio", "bucket", default="archive")
    region = minio_config.get("region", "us-east-1")
    try:
        storage_client.create_root_storage(bucket_name, region)
        log.info("Initializing bucket %s", bucket_name)
    except BucketAlreadyExistsError:
        pass


@cli.command()
@click.option("--name", envvar="HOSTNAME", default="worker", help="Node name")
@click.option(
    "--concurrency", type=int, default=2, help="Number for celery concurrency"
)
@click.option("--debug", is_flag=True, default=False, help="Enable celery debug mode")
@click.option(
    "--queue",
    multiple=True,
    default=["celery"],
    help="Queues to listen to for this worker",
)
def worker(name, concurrency, debug, queue):
    setup_worker()
    actual_queues = _get_queues_param_from_queue_input(queue)
    return app.celery_app.worker_main(
        argv=[
            "worker",
            "-n",
            name,
            "-c",
            concurrency,
            "-l",
            ("debug" if debug else "info"),
            "-Q",
            actual_queues,
            "-B",
            "-s",
            "/home/codecov/celerybeat-schedule",  # TODO find file that can work on production and enterprise
        ]
    )


def _get_queues_param_from_queue_input(queues: typing.List[str]) -> str:
    # this should support if one wants to pass comma separated values
    # since in the end all is joined again
    return ",".join(queues)


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
