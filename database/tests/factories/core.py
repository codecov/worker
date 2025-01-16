from datetime import datetime, timezone
from hashlib import sha1
from uuid import uuid4

import factory
from factory import Factory
from shared.plan.constants import PlanName

from database import enums, models
from services.encryption import encryptor


def encrypt_oauth_token(val):
    if val is None:
        return None
    return encryptor.encode(val)


class UserFactory(Factory):
    class Meta:
        model = models.User

    id_ = factory.Sequence(lambda n: n)

    name = factory.Faker("name")
    email = factory.Faker("email")
    is_staff = False
    is_superuser = False
    external_id = factory.LazyFunction(lambda: uuid4())


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
    service = factory.Iterator(["gitlab", "github", "bitbucket"])
    free = 0
    unencrypted_oauth_token = factory.LazyFunction(lambda: uuid4().hex)
    trial_start_date = datetime.now()
    trial_end_date = datetime.now()
    trial_status = enums.TrialStatus.NOT_STARTED.value
    trial_fired_by = None
    upload_token_required_for_public_repos = False
    plan = PlanName.BASIC_PLAN_NAME.value

    oauth_token = factory.LazyAttribute(
        lambda o: encrypt_oauth_token(o.unencrypted_oauth_token)
    )

    @classmethod
    def create_from_test_request(cls, request, *args, **kwargs):
        if "username" not in kwargs:
            kwargs["username"] = request.node.name[-100:]
        return cls(*args, **kwargs)


class RepositoryFactory(Factory):
    class Meta:
        model = models.Repository

    private = True
    name = factory.Faker("slug")
    using_integration = False
    service_id = factory.Sequence(lambda n: "id_%d" % n)

    owner = factory.SubFactory(OwnerFactory)
    bot = None
    updatestamp = factory.LazyAttribute(lambda o: datetime.now(tz=timezone.utc))
    languages = []
    languages_last_updated = factory.LazyAttribute(
        lambda o: datetime.now(tz=timezone.utc)
    )
    bundle_analysis_enabled = False
    test_analytics_enabled = True


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
    author = factory.SubFactory(OwnerFactory)


class CommitFactory(Factory):
    class Meta:
        model = models.Commit

    message = factory.Faker("sentence")

    id_ = factory.Sequence(lambda n: n)
    commitid = factory.LazyAttribute(
        lambda o: sha1(
            (o.message if o.message is not None else "nomessage").encode("utf-8")
        ).hexdigest()
    )
    ci_passed = True
    pullid = None
    timestamp = datetime(2019, 2, 1, 17, 59, 47, tzinfo=timezone.utc)
    author = factory.SubFactory(OwnerFactory)
    repository = factory.SubFactory(RepositoryFactory)
    totals = factory.LazyFunction(
        lambda: {
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
    )
    _report_json_storage_path = None
    _report_json = factory.LazyFunction(
        lambda: {
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
    )
    parent_commit_id = factory.LazyAttribute(
        lambda o: sha1(
            (o.message if o.message is not None else "nomessage" + "parent").encode(
                "utf-8"
            )
        ).hexdigest()
    )
    state = "complete"


class ReportFactory(Factory):
    class Meta:
        model = models.CommitReport

    commit = factory.SubFactory(CommitFactory)


class ReportLevelTotalsFactory(Factory):
    class Meta:
        model = models.ReportLevelTotals

    report = factory.SubFactory(ReportFactory)
    branches = 0
    coverage = 0.00
    hits = 0
    lines = 0
    methods = 0
    misses = 0
    partials = 0
    files = 0


class ReportDetailsFactory(Factory):
    class Meta:
        model = models.ReportDetails

    report = factory.SubFactory(ReportFactory)
    _files_array = factory.LazyFunction(list)


class ReportResultsFactory(Factory):
    class Meta:
        model = models.ReportResults

    report = factory.SubFactory(ReportFactory)
    state = "success"
    result = {"state": "success", "message": "somemessage"}


class UploadFactory(Factory):
    class Meta:
        model = models.Upload

    report = factory.SubFactory(ReportFactory)
    state = "complete"
    upload_extras = {}
    upload_type = "uploaded"
    storage_path = "storage/path.txt"
    created_at = datetime.now()


class UploadLevelTotalsFactory(Factory):
    class Meta:
        model = models.UploadLevelTotals

    upload = factory.SubFactory(UploadFactory)
    branches = 0
    coverage = 0.00
    hits = 0
    lines = 0
    methods = 0
    misses = 0
    partials = 0
    files = 0


class RepositoryFlagFactory(Factory):
    class Meta:
        model = models.RepositoryFlag

    repository = factory.SubFactory(RepositoryFactory)
    flag_name = "test_flag"


class CommitNotificationFactory(Factory):
    class Meta:
        model = models.CommitNotification

    notification_type = enums.Notification.comment
    decoration_type = enums.Decoration.standard
    state = enums.NotificationState.pending

    commit = factory.SubFactory(CommitFactory)


class CompareCommitFactory(Factory):
    class Meta:
        model = models.CompareCommit

    state = enums.CompareCommitState.pending.value
    base_commit = factory.SubFactory(CommitFactory)
    compare_commit = factory.SubFactory(CommitFactory)


class OrgLevelTokenFactory(Factory):
    class Meta:
        model = models.OrganizationLevelToken

    token = factory.LazyFunction(lambda: uuid4().hex)
    token_type = "upload"
    owner = factory.SubFactory(OwnerFactory)


class ConstantsFactory(Factory):
    class Meta:
        model = models.Constants

    key = ""
    value = ""
