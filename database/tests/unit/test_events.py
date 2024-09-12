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
    repo = RepositoryFactory(repoid=91728376, name="test-123")
    dbsession.add(repo)
    dbsession.commit()

    publish.assert_called_once_with(
        "projects/test-project-id/topics/test-topic-id",
        b'{"type": "repo", "sync": "one", "id": 91728376}',
    )

    publish = mocker.patch("google.cloud.pubsub_v1.PublisherClient.publish")

    # Synchronize object flush for history.deleted to be perceived by sqlalchemy
    dbsession.refresh(repo)

    # this triggers the publish via SQLAlchemy events (after_update)
    repo.name = "test-456"
    dbsession.commit()

    # same name shouldn't trigger (after_update)
    repo.name = "test-456"
    dbsession.commit()

    # this wouldn't trigger the publish via SQLAlchemy events (after_update) since it's an unimportant attribute
    repo.activated = True
    dbsession.commit()

    # this is from the first trigger
    publish.assert_called_once_with(
        "projects/test-project-id/topics/test-topic-id",
        b'{"type": "repo", "sync": "one", "id": 91728376}',
    )
