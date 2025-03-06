import json

import pytest

from database.tests.factories import OwnerFactory, RepositoryFactory
from services.ai_pr_review import Diff, LineInfo, perform_review
from services.archive import ArchiveService

TEST_DIFF = """diff --git a/codecov_auth/signals.py b/codecov_auth/signals.py
index d728f92f..37f333fb 100644
--- a/codecov_auth/signals.py
+++ b/codecov_auth/signals.py
@@ -1,10 +1,13 @@
+import json
 import logging
 from datetime import datetime
 
+from django.conf import settings
 from django.db.models.signals import post_save
 from django.dispatch import receiver
+from google.cloud import pubsub_v1
 
-from codecov_auth.models import Owner, OwnerProfile
+from codecov_auth.models import OrganizationLevelToken, Owner, OwnerProfile
 
 
 @receiver(post_save, sender=Owner)
@@ -13,3 +16,34 @@ def create_owner_profile_when_owner_is_created(
 ):
     if created:
         return OwnerProfile.objects.create(owner_id=instance.ownerid)
+
+
+_pubsub_publisher = None
+
+
+def _get_pubsub_publisher():
+    global _pubsub_publisher
+    if not _pubsub_publisher:
+        _pubsub_publisher = pubsub_v1.PublisherClient()
+    return _pubsub_publisher
+
+
+@receiver(
+    post_save, sender=OrganizationLevelToken, dispatch_uid="shelter_sync_org_token"
+)
+def update_repository(sender, instance: OrganizationLevelToken, **kwargs):
+    pubsub_project_id = settings.SHELTER_PUBSUB_PROJECT_ID
+    topic_id = settings.SHELTER_PUBSUB_SYNC_REPO_TOPIC_ID
+    if pubsub_project_id and topic_id:
+        publisher = _get_pubsub_publisher()
+        topic_path = publisher.topic_path(pubsub_project_id, topic_id)
+        publisher.publish(
+            topic_path,
+            json.dumps(
+                {
+                    "type": "org_token",
+                    "sync": "one",
+                    "id": instance.id,
+                }
+            ).encode("utf-8"),
+        )
diff --git a/codecov_auth/tests/test_signals.py b/codecov_auth/tests/test_signals.py
new file mode 100644
index 00000000..b2fb0642
--- /dev/null
+++ b/codecov_auth/tests/test_signals.py
@@ -0,0 +1,26 @@
+import os
+
+import pytest
+from django.test import override_settings
+
+from codecov_auth.tests.factories import OrganizationLevelTokenFactory
+
+
+@override_settings(
+    SHELTER_PUBSUB_PROJECT_ID="test-project-id",
+    SHELTER_PUBSUB_SYNC_REPO_TOPIC_ID="test-topic-id",
+)
+@pytest.mark.django_db
+def test_shelter_org_token_sync(mocker):
+    # this prevents the pubsub SDK from trying to load credentials
+    os.environ["PUBSUB_EMULATOR_HOST"] = "localhost"
+
+    publish = mocker.patch("google.cloud.pubsub_v1.PublisherClient.publish")
+
+    # this triggers the publish via Django signals
+    OrganizationLevelTokenFactory(id=91728376)
+
+    publish.assert_called_once_with(
+        "projects/test-project-id/topics/test-topic-id",
+        b'{"type": "org_token", "sync": "one", "id": 91728376}',
+    )
diff --git a/core/signals.py b/core/signals.py
index 77500d63..adffea32 100644
--- a/core/signals.py
+++ b/core/signals.py
@@ -18,12 +18,19 @@ def _get_pubsub_publisher():
 
 
 @receiver(post_save, sender=Repository, dispatch_uid="shelter_sync_repo")
-def update_repository(sender, instance, **kwargs):
+def update_repository(sender, instance: Repository, **kwargs):
     pubsub_project_id = settings.SHELTER_PUBSUB_PROJECT_ID
     topic_id = settings.SHELTER_PUBSUB_SYNC_REPO_TOPIC_ID
     if pubsub_project_id and topic_id:
         publisher = _get_pubsub_publisher()
         topic_path = publisher.topic_path(pubsub_project_id, topic_id)
         publisher.publish(
-            topic_path, json.dumps({"sync": instance.repoid}).encode("utf-8")
+            topic_path,
+            json.dumps(
+                {
+                    "type": "repo",
+                    "sync": "one",
+                    "id": instance.repoid,
+                }
+            ).encode("utf-8"),
         )
diff --git a/core/tests/test_signals.py b/core/tests/test_signals.py
index b6eafc65..26a8c8e2 100644
--- a/core/tests/test_signals.py
+++ b/core/tests/test_signals.py
@@ -21,5 +21,6 @@ def test_shelter_repo_sync(mocker):
     RepositoryFactory(repoid=91728376)
 
     publish.assert_called_once_with(
-        "projects/test-project-id/topics/test-topic-id", b'{"sync": 91728376}'
+        "projects/test-project-id/topics/test-topic-id",
+        b'{"type": "repo", "sync": "one", "id": 91728376}',
     )
"""

config_params = {
    "services": {
        "openai": {
            "api_key": "placeholder",  # replace this temporarily if you need to regenerate the VCR cassettes
        },
        "minio": {
            "hash_key": "test-hash",
        },
    },
}

torngit_token = {
    "key": "placeholder",  # replace this temporarily if you need to regenerate the VCR cassettes
    "secret": None,
    "username": "scott-codecov",
}


def test_review_index():
    diff = Diff(TEST_DIFF)
    assert diff.line_info(29) == LineInfo(
        file_path="codecov_auth/signals.py", position=23
    )
    assert diff.line_info(123) == LineInfo(
        file_path="core/tests/test_signals.py", position=6
    )


@pytest.mark.asyncio
async def test_perform_initial_review(
    dbsession, codecov_vcr, mocker, mock_configuration, mock_storage
):
    mock_configuration.set_params(config_params)

    bot_token = mocker.patch("shared.bots.repo_bots.get_repo_particular_bot_token")
    bot_token.return_value = (torngit_token, None)

    owner = OwnerFactory.create(service="github", username="scott-codecov")
    repository = RepositoryFactory.create(owner=owner, name="codecov-test")
    dbsession.add(owner)
    dbsession.add(repository)
    dbsession.commit()

    archive = ArchiveService(repository)

    await perform_review(repository, 40)

    assert json.loads(
        mock_storage.read_file(
            "archive", f"ai_pr_review/{archive.storage_hash}/pull_40.json"
        )
    ) == {
        "commit_sha": "b607bb0e17e1b8d8699272a26e32986a933f9946",
        "review_ids": [1740008775],
    }


@pytest.mark.asyncio
async def test_perform_duplicate_review(
    dbsession, codecov_vcr, mocker, mock_configuration, mock_storage
):
    mock_configuration.set_params(config_params)

    bot_token = mocker.patch("shared.bots.repo_bots.get_repo_particular_bot_token")
    bot_token.return_value = (torngit_token, None)

    owner = OwnerFactory(service="github", username="scott-codecov")
    repository = RepositoryFactory(owner=owner, name="codecov-test")
    dbsession.add(owner)
    dbsession.add(repository)
    dbsession.commit()

    archive = ArchiveService(repository)

    mock_storage.write_file(
        "archive",
        f"ai_pr_review/{archive.storage_hash}/pull_40.json",
        json.dumps(
            {
                "commit_sha": "b607bb0e17e1b8d8699272a26e32986a933f9946",
                "review_ids": [1740008775],
            }
        ),
    )

    perform = mocker.patch("services.ai_pr_review.Review.perform")
    perform.return_value = None

    await perform_review(repository, 40)

    # noop - we already made a review for this sha
    assert not perform.called


@pytest.mark.asyncio
async def test_perform_new_commit(
    dbsession, codecov_vcr, mocker, mock_configuration, mock_storage
):
    mock_configuration.set_params(config_params)

    bot_token = mocker.patch("shared.bots.repo_bots.get_repo_particular_bot_token")
    bot_token.return_value = (torngit_token, None)

    owner = OwnerFactory(service="github", username="scott-codecov")
    repository = RepositoryFactory(owner=owner, name="codecov-test")
    dbsession.add(owner)
    dbsession.add(repository)
    dbsession.commit()

    archive = ArchiveService(repository)

    mock_storage.write_file(
        "archive",
        f"ai_pr_review/{archive.storage_hash}/pull_40.json",
        json.dumps(
            {
                "commit_sha": "b607bb0e17e1b8d8699272a26e32986a933f9946",
                "review_ids": [1740008775],
            }
        ),
    )

    await perform_review(repository, 40)

    assert json.loads(
        mock_storage.read_file(
            "archive",
            f"ai_pr_review/{archive.storage_hash}/pull_40.json",
        )
    ) == {
        "commit_sha": "5c64a5143951193dde7b14c14611eebe1025f862",
        "review_ids": [1740008775, 1740017976],
    }
