import json
import logging

from google.cloud import pubsub_v1
from shared.config import get_config
from sqlalchemy import event, inspect

from database.models.core import Repository
from helpers.environment import is_enterprise

_pubsub_publisher = None

log = logging.getLogger(__name__)


def _is_shelter_enabled():
    return get_config(
        "setup", "shelter", "enabled", default=False if is_enterprise() else True
    )


def _get_pubsub_publisher():
    global _pubsub_publisher
    if not _pubsub_publisher:
        _pubsub_publisher = pubsub_v1.PublisherClient()
    return _pubsub_publisher


def _sync_repo(repository: Repository):
    log.info(f"Signal triggered for repository {repository.repoid}")
    try:
        pubsub_project_id = get_config("setup", "shelter", "pubsub_project_id")
        pubsub_topic_id = get_config("setup", "shelter", "sync_repo_topic_id")

        if pubsub_project_id and pubsub_topic_id:
            publisher = _get_pubsub_publisher()
            topic_path = publisher.topic_path(pubsub_project_id, pubsub_topic_id)
            publisher.publish(
                topic_path,
                json.dumps(
                    {
                        "type": "repo",
                        "sync": "one",
                        "id": repository.repoid,
                    }
                ).encode("utf-8"),
            )
        log.info(f"Message published for repository {repository.repoid}")
    except Exception as e:
        log.warning(f"Failed to publish message for repo {repository.repoid}: {e}")


@event.listens_for(Repository, "after_insert")
def after_insert_repo(mapper, connection, target: Repository):
    if not _is_shelter_enabled():
        log.debug("Shelter is not enabled, skipping after_insert signal")
        return

    # Send to shelter service
    log.info("After insert signal", extra=dict(repoid=target.repoid))
    _sync_repo(target)


@event.listens_for(Repository, "after_update")
def after_update_repo(mapper, connection, target: Repository):
    if not _is_shelter_enabled():
        log.debug("Shelter is not enabled, skipping after_update signal")
        return

    # Send to shelter service
    state = inspect(target)

    for attr in state.attrs:
        if attr.key in ["name", "upload_token"]:
            history = attr.history
            # Detects if there are changes and if said changes are different.
            # has_changes() is True when you update the an entry with the same value,
            # so we must ensure those values are different to trigger the signal
            if history.has_changes() and history.deleted and history.added:
                old_value = history.deleted[0]
                new_value = history.added[0]
                if old_value != new_value:
                    log.info("After update signal", extra=dict(repoid=target.repoid))
                    _sync_repo(target)
                    break
