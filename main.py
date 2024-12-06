import os

import django

# we're moving this before we create the Celery object
# so that celery can detect Django is being used
# using the Django fixup will help fix some database issues
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_scaffold.settings")
django.setup()

# -*- coding: utf-8 -*-
import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import typing  # noqa: E402

import click  # noqa: E402
from celery.signals import worker_process_shutdown  # noqa: E402
from prometheus_client import REGISTRY, CollectorRegistry, multiprocess  # noqa: E402
from shared.celery_config import BaseCeleryConfig  # noqa: E402
from shared.config import get_config  # noqa: E402
from shared.license import startup_license_logging  # noqa: E402
from shared.metrics import start_prometheus  # noqa: E402
from shared.storage.exceptions import BucketAlreadyExistsError  # noqa: E402

import app  # noqa: E402
from helpers.environment import get_external_dependencies_folder  # noqa: E402
from helpers.version import get_current_version  # noqa: E402
from services.storage import get_storage_client  # noqa: E402

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


@worker_process_shutdown.connect
def mark_process_dead(pid, exitcode, **kwargs):
    multiprocess.mark_process_dead(pid)


def setup_worker():
    print(initialization_text.format(version=get_current_version()))

    if getattr(sys, "frozen", False):
        # Only for enterprise builds
        external_deps_folder = get_external_dependencies_folder()
        log.info(f"External dependencies folder configured to {external_deps_folder}")
        sys.path.append(external_deps_folder)

    registry = REGISTRY
    if "PROMETHEUS_MULTIPROC_DIR" in os.environ:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)

    start_prometheus(9996, registry=registry)  # 9996 is an arbitrary port number

    storage_client = get_storage_client()
    minio_config = get_config("services", "minio")
    bucket_name = get_config("services", "minio", "bucket", default="archive")
    auto_create_bucket = get_config(
        "services", "minio", "auto_create_bucket", default=False
    )
    region = minio_config.get("region", "us-east-1")
    try:
        # note that this is a departure from the old default behavior.
        # This is intended as the bucket will exist in most cases where IAC or manual setup is used
        if auto_create_bucket:
            storage_client.create_root_storage(bucket_name, region)
            log.info("Initializing bucket %s", bucket_name)
    except BucketAlreadyExistsError:
        pass

    startup_license_logging()


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
    args = [
        "worker",
        "-n",
        name,
        "-c",
        concurrency,
        "-l",
        ("debug" if debug else "info"),
    ]
    if get_config("setup", "celery_queues_enabled", default=True):
        actual_queues = _get_queues_param_from_queue_input(queue)
        args += [
            "-Q",
            actual_queues,
        ]
    if get_config("setup", "celery_beat_enabled", default=True):
        args += ["-B", "-s", "/home/codecov/celerybeat-schedule"]
    return app.celery_app.worker_main(argv=args)


def _get_queues_param_from_queue_input(queues: typing.List[str]) -> str:
    # We always run the health_check queue to make sure the healthcheck is performed
    # And also to avoid that queue fillign up with no workers to consume from it
    # this should support if one wants to pass comma separated values
    # since in the end all is joined again
    joined_queues = ",".join(queues)
    enterprise_queues = ["enterprise_" + q for q in joined_queues.split(",")]
    return ",".join(
        [joined_queues, *enterprise_queues, BaseCeleryConfig.health_check_default_queue]
    )


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
