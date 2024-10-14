from shared.rollouts import Feature

# Declare the feature variants and parameters via Django Admin
FLAKY_TEST_DETECTION = Feature("flaky_test_detection")
FLAKY_SHADOW_MODE = Feature("flaky_shadow_mode")

PARALLEL_UPLOAD_PROCESSING_BY_REPO = Feature("parallel_upload_processing")

CARRYFORWARD_BASE_SEARCH_RANGE_BY_OWNER = Feature("carryforward_base_search_range")

SYNC_PULL_USE_MERGE_COMMIT_SHA = Feature("sync_pull_use_merge_commit_sha")
