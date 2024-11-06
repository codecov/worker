from shared.rollouts import Feature

# Declare the feature variants and parameters via Django Admin
FLAKY_TEST_DETECTION = Feature("flaky_test_detection")
FLAKY_SHADOW_MODE = Feature("flaky_shadow_mode")

# Eventually we want all repos to use this
# This flag will just help us with the rollout process
USE_LABEL_INDEX_IN_REPORT_PROCESSING_BY_REPO_ID = Feature(
    "use_label_index_in_report_processing"
)

INTERMEDIATE_REPORTS_IN_REDIS = Feature("intermediate_reports_in_redis")

CARRYFORWARD_BASE_SEARCH_RANGE_BY_OWNER = Feature("carryforward_base_search_range")

SYNC_PULL_USE_MERGE_COMMIT_SHA = Feature("sync_pull_use_merge_commit_sha")

CHECKPOINT_ENABLED_REPOSITORIES = Feature("checkpoint_enabled_repositories")
