import json

from google.cloud import pubsub_v1
from shared.config import get_config
from sqlalchemy import event

from database.models.core import Repository

_pubsub_publisher = None


def _get_pubsub_publisher():
    global _pubsub_publisher
    if not _pubsub_publisher:
        _pubsub_publisher = pubsub_v1.PublisherClient()
    return _pubsub_publisher


def _sync_repo(repository: Repository):
    pubsub_project_id = get_config("setup", "shelter", "pubsub_project_id")
    pubsub_topic_id = get_config("setup", "shelter", "sync_repo_topic_id")

    if pubsub_project_id and pubsub_topic_id:
        publisher = _get_pubsub_publisher()
        topic_path = publisher.topic_path(pubsub_project_id, pubsub_topic_id)
        publisher.publish(
            topic_path, json.dumps({"sync": repository.repoid}).encode("utf-8")
        )


@event.listens_for(Repository, "after_insert")
def after_insert_repo(mapper, connection, target):
    _sync_repo(target)


@event.listens_for(Repository, "after_update")
def after_update_repo(mapper, connection, target):
    _sync_repo(target)
