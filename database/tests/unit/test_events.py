import os

import database.events  # noqa: F401
from database.tests.factories import OwnerFactory, RepositoryFactory


def test_shelter_repo_sync(dbsession, mock_configuration, mocker):
    # this prevents the pubsub SDK from trying to load credentials
    os.environ["PUBSUB_EMULATOR_HOST"] = "localhost"
    publish = mocker.patch("google.cloud.pubsub_v1.PublisherClient.publish")

    mock_configuration.set_params(
        {
            "setup": {
                "shelter": {
                    "pubsub_project_id": "test-project-id",
                    "sync_repo_topic_id": "test-topic-id",
                    "enabled": True,
                }
            }
        }
    )

    # this triggers the publish via SQLAlchemy events (after_insert)
    repo = RepositoryFactory(
        repoid=91728376, name="test-123", owner=OwnerFactory(ownerid=123), private=False
    )
    dbsession.add(repo)
    dbsession.commit()

    publish.assert_called_once_with(
        "projects/test-project-id/topics/test-topic-id",
        b'{"type": "repo", "sync": "one", "id": 91728376}',
    )
    publish_calls = publish.call_args_list

    # Synchronize object flush for history.deleted to be perceived by sqlalchemy
    dbsession.refresh(repo)

    # this triggers the publish via SQLAlchemy events (after_update)
    repo.name = "test-456"
    dbsession.commit()
    dbsession.refresh(repo)
    assert len(publish_calls) == 2

    # Does not trigger another publish with untracked field
    repo.message = "foo"
    dbsession.commit()
    dbsession.refresh(repo)
    assert len(publish_calls) == 2

    # Triggers call when owner is changed
    repo.owner = OwnerFactory(ownerid=456)
    dbsession.commit()
    dbsession.refresh(repo)
    assert len(publish_calls) == 3

    # Triggers call when private is changed
    repo.private = True
    dbsession.commit()
    dbsession.refresh(repo)
    assert len(publish_calls) == 4


def test_repo_sync_when_shelter_disabled(dbsession, mock_configuration, mocker):
    # this prevents the pubsub SDK from trying to load credentials
    os.environ["PUBSUB_EMULATOR_HOST"] = "localhost"

    mock_configuration.set_params(
        {
            "setup": {
                "shelter": {
                    "pubsub_project_id": "test-project-id",
                    "sync_repo_topic_id": "test-topic-id",
                    "enabled": False,
                }
            }
        }
    )

    publish = mocker.patch("google.cloud.pubsub_v1.PublisherClient.publish")

    # Create new repo with shelter disabled
    repo = RepositoryFactory(repoid=91728377, name="test-789")
    dbsession.add(repo)
    dbsession.commit()

    # Verify no publish was called when shelter is disabled
    publish.assert_not_called()
