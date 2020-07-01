from uuid import uuid4
from datetime import datetime

import factory
from database import models
from hashlib import sha1
from factory import Factory, fuzzy

from services.encryption import encryptor


def encrypt_oauth_token(val):
    if val is None:
        return None
    return encryptor.encode(val)


class OwnerFactory(Factory):
    class Meta:
        model = models.Owner
        exclude = ("unencrypted_oauth_token",)

    name = factory.Faker("name")
    email = factory.Faker("email")
    username = factory.Faker("user_name")
    plan_activated_users = []
    service_id = factory.Sequence(lambda n: "user%d" % n)
    admins = []
    permission = []
    organizations = []
    service = "github"
    free = 0
    unencrypted_oauth_token = factory.LazyFunction(lambda: uuid4().hex)

    oauth_token = factory.LazyAttribute(
        lambda o: encrypt_oauth_token(o.unencrypted_oauth_token)
    )


class RepositoryFactory(Factory):
    class Meta:
        model = models.Repository

    private = True
    name = factory.Faker("slug")
    using_integration = False
    service_id = factory.Sequence(lambda n: "id_%d" % n)

    owner = factory.SubFactory(OwnerFactory)
    bot = None


class BranchFactory(Factory):
    class Meta:
        model = models.Branch

    branch = factory.Faker("slug")
    head = factory.LazyAttribute(lambda o: sha1(o.branch.encode("utf-8")).hexdigest())
    authors = []

    repository = factory.SubFactory(RepositoryFactory)


class PullFactory(Factory):
    class Meta:
        model = models.Pull

    pullid = factory.Sequence(lambda n: 10 + (7 * n) % 90)
    state = "open"

    repository = factory.SubFactory(RepositoryFactory)


class CommitFactory(Factory):
    class Meta:
        model = models.Commit

    message = factory.Faker("sentence")

    commitid = factory.LazyAttribute(
        lambda o: sha1(o.message.encode("utf-8")).hexdigest()
    )
    ci_passed = True
    pullid = 1
    timestamp = datetime(2019, 2, 1, 17, 59, 47)
    author = factory.SubFactory(OwnerFactory)
    repository = factory.SubFactory(RepositoryFactory)
    totals = {
        "C": 0,
        "M": 0,
        "N": 0,
        "b": 0,
        "c": "85.00000",
        "d": 0,
        "diff": [1, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
        "f": 3,
        "h": 17,
        "m": 3,
        "n": 20,
        "p": 0,
        "s": 1,
    }
    report_json = {
        "files": {
            "awesome/__init__.py": [
                2,
                [0, 10, 8, 2, 0, "80.00000", 0, 0, 0, 0, 0, 0, 0],
                [[0, 10, 8, 2, 0, "80.00000", 0, 0, 0, 0, 0, 0, 0]],
                [0, 2, 1, 1, 0, "50.00000", 0, 0, 0, 0, 0, 0, 0],
            ],
            "tests/__init__.py": [
                0,
                [0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0],
                [[0, 3, 2, 1, 0, "66.66667", 0, 0, 0, 0, 0, 0, 0]],
                None,
            ],
            "tests/test_sample.py": [
                1,
                [0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                [[0, 7, 7, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0]],
                None,
            ],
        },
        "sessions": {
            "0": {
                "N": None,
                "a": "v4/raw/2019-01-10/4434BC2A2EC4FCA57F77B473D83F928C/abf6d4df662c47e32460020ab14abf9303581429/9ccc55a1-8b41-4bb1-a946-ee7a33a7fb56.txt",
                "c": None,
                "d": 1547084427,
                "e": None,
                "f": ["unit"],
                "j": None,
                "n": None,
                "p": None,
                "t": [3, 20, 17, 3, 0, "85.00000", 0, 0, 0, 0, 0, 0, 0],
                "": None,
            }
        },
    }
    parent_commit_id = factory.LazyAttribute(
        lambda o: sha1((o.message + "parent").encode("utf-8")).hexdigest()
    )
    state = "complete"
