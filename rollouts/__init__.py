from shared.rollouts import Feature

# Declare the feature variants and parameters via Django Admin
FLAKY_TEST_DETECTION = Feature("flaky_test_detection")
FLAKY_SHADOW_MODE = Feature("flaky_shadow_mode")

INTERMEDIATE_REPORTS_IN_REDIS = Feature("intermediate_reports_in_redis")

CARRYFORWARD_BASE_SEARCH_RANGE_BY_OWNER = Feature("carryforward_base_search_range")

SYNC_PULL_USE_MERGE_COMMIT_SHA = Feature("sync_pull_use_merge_commit_sha")

CHECKPOINT_ENABLED_REPOSITORIES = Feature("checkpoint_enabled_repositories")
