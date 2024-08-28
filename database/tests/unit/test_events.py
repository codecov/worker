import os

import database.events  # noqa: F401
from database.tests.factories import RepositoryFactory


def test_shelter_repo_sync(dbsession, mock_configuration, mocker):
    # this prevents the pubsub SDK from trying to load credentials
    os.environ["PUBSUB_EMULATOR_HOST"] = "localhost"

    mock_configuration.set_params(
        {
            "setup": {
                "shelter": {
                    "pubsub_project_id": "test-project-id",
                    "sync_repo_topic_id": "test-topic-id",
                }
            }
        }
    )

    publish = mocker.patch("google.cloud.pubsub_v1.PublisherClient.publish")

    # this triggers the publish via SQLAlchemy events (after_insert)
    repo = RepositoryFactory(repoid=91728376)
    dbsession.add(repo)
    dbsession.commit()

    publish.assert_called_once_with(
        "projects/test-project-id/topics/test-topic-id",
        b'{"type": "repo", "sync": "one", "id": 91728376}',
    )

    publish = mocker.patch("google.cloud.pubsub_v1.PublisherClient.publish")

    # this triggers the publish via SQLAlchemy events (after_update)
    repo.name = "testing"
    dbsession.commit()

    publish.assert_called_once_with(
        "projects/test-project-id/topics/test-topic-id",
        b'{"type": "repo", "sync": "one", "id": 91728376}',
    )
