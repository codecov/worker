from shared.rollouts import Feature

from database.models import Owner, Repository


def owner_slug(owner: Owner) -> str:
    return f"{owner.service}/{owner.username}"


def repo_slug(repo: Repository) -> str:
    return f"{repo.service}/{repo.owner.username}/{repo.name}"


# Declare the feature variants via Django Admin
LIST_REPOS_GENERATOR_BY_OWNER_ID = Feature(
    "list_repos_generator",
    0.0,
)

# Eventually we want all repos to use this
# This flag will just help us with the rollout process
USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID = Feature(
    "use_label_index_in_report_processing",
    0.0,
)
