from shared.rollouts import Feature, FeatureVariant

from database.models import Owner, Repository


def owner_slug(owner: Owner) -> str:
    return f"{owner.service}/{owner.username}"


def repo_slug(repo: Repository) -> str:
    return f"{repo.service}/{repo.owner.username}/{repo.name}"

# By default, features have one variant:
#    { "enabled": FeatureVariant(True, 1.0) }
PARALLEL_UPLOAD_PROCESSING_BY_REPO = Feature(
    "parallel_upload_processing",
    0.0,
    overrides={
        "github/codecov/worker",
    },
)
