from shared.rollouts import Feature

# Declare the feature variants and parameters via Django Admin
FLAKY_TEST_DETECTION = Feature("flaky_test_detection")

CARRYFORWARD_BASE_SEARCH_RANGE_BY_OWNER = Feature("carryforward_base_search_range")

SYNC_PULL_USE_MERGE_COMMIT_SHA = Feature("sync_pull_use_merge_commit_sha")

CHECKPOINT_ENABLED_REPOSITORIES = Feature("checkpoint_enabled_repositories")

SHOW_IMPACT_ANALYSIS_DEPRECATION_MSG = Feature(
    "show_impact_analysis_deprecation_message"
)

NEW_TA_TASKS = Feature("new_ta_tasks")

PARALLEL_COMPONENT_COMPARISON = Feature("parallel_component_comparison")

TA_TIMESERIES = Feature("ta_timeseries")
