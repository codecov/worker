from shared.rollouts import Feature

from database.models import Owner, Repository

# Declare the feature variants and parameters via Django Admin
LIST_REPOS_GENERATOR_BY_OWNER_ID = Feature("list_repos_generator")

BULK_INSERT_TEST_INSTANCES = Feature("bulk_insert_test_instances")

# Eventually we want all repos to use this
# This flag will just help us with the rollout process
USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID = Feature(
    "use_label_index_in_report_processing"
)

PARALLEL_UPLOAD_PROCESSING_BY_REPO = Feature("parallel_upload_processing")

CARRYFORWARD_BASE_SEARCH_RANGE_BY_OWNER = Feature("carryforward_base_search_range")
