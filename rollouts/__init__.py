from shared.rollouts import Feature, FeatureVariant

from database.models import Owner, Repository


def owner_slug(owner: Owner) -> str:
    return f"{owner.service}/{owner.username}"


def repo_slug(repo: Repository) -> str:
    return f"{repo.service}/{repo.owner.username}/{repo.name}"


# By default, features have one variant:
#    { "enabled": FeatureVariant(True, 1.0) }
LIST_REPOS_GENERATOR_BY_OWNER_SLUG = Feature(
    "list_repos_generator",
    0.0,
    overrides={
        "github/codecov": "enabled",
        "bitbucket/codecov": "enabled",
        "gitlab/codecov": "enabled",
    },
)

# Eventually we want all repos to use this
# This flag will just help us with the rollout process
USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_SLUG = Feature(
    "use_label_index_in_report_processing",
    0.0,
    overrides={
        "github/giovanni-guidini/sentry": "enabled",
        "github/giovanni-guidini/components-demo": "enabled",
    },
)
