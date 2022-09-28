from shared.analytics_tracking import (
    track_betaprofiling_added_in_YAML,
    track_betaprofiling_removed_from_YAML,
    track_manual_critical_file_labelling_added_in_YAML,
    track_manual_critical_file_labelling_removed_from_YAML,
    track_show_critical_paths_added_in_YAML,
    track_show_critical_paths_removed_from_YAML,
)

from helpers.environment import is_enterprise
from services.yaml.reader import read_yaml_field


def tracking_yaml_fields_changes(existing_yaml, new_yaml, repository):
    """Controls what tracking functions are being used for yaml field changes"""
    _track_betaprofiling(existing_yaml, new_yaml, repository)
    _track_show_critical_paths(existing_yaml, new_yaml, repository)
    _track_manual_critical_file_labelling_events(existing_yaml, new_yaml, repository)


def _track_betaprofiling(existing_yaml, new_yaml, repository):
    existing_comment_layout_field = read_yaml_field(
        existing_yaml, ("comment", "layout")
    )
    new_comment_layout_field = read_yaml_field(new_yaml, ("comment", "layout"))

    existing_comment_sections = list(
        map(lambda l: l.strip(), (existing_comment_layout_field or "").split(","))
    )
    new_comment_sections = list(
        map(lambda l: l.strip(), (new_comment_layout_field or "").split(","))
    )

    if _was_betaprofiling_added_in_yaml(
        existing_comment_sections, new_comment_sections
    ):
        track_betaprofiling_added_in_YAML(
            repository.repoid, repository.ownerid, is_enterprise()
        )

    if _was_betaprofiling_removed_from_yaml(
        existing_comment_sections, new_comment_sections
    ):
        track_betaprofiling_removed_from_YAML(
            repository.repoid, repository.ownerid, is_enterprise()
        )


def _was_betaprofiling_added_in_yaml(existing_comment_sections, new_comment_sections):
    return (
        "betaprofiling" not in existing_comment_sections
        and "betaprofiling" in new_comment_sections
    )


def _was_betaprofiling_removed_from_yaml(
    existing_comment_sections, new_comment_sections
):
    return (
        "betaprofiling" in existing_comment_sections
        and "betaprofiling" not in new_comment_sections
    )


def _track_show_critical_paths(existing_yaml, new_yaml, repository):
    existing_show_critical_paths = read_yaml_field(
        existing_yaml, ("comment", "show_critical_paths")
    )
    new_show_critical_paths = read_yaml_field(
        new_yaml, ("comment", "show_critical_paths")
    )

    if not existing_show_critical_paths and new_show_critical_paths:
        track_show_critical_paths_added_in_YAML(
            repository.repoid, repository.ownerid, is_enterprise()
        )
    if existing_show_critical_paths and not new_show_critical_paths:
        track_show_critical_paths_removed_from_YAML(
            repository.repoid, repository.ownerid, is_enterprise()
        )


def _track_manual_critical_file_labelling_events(existing_yaml, new_yaml, repository):
    existing_critical_paths_field = read_yaml_field(
        existing_yaml, ("profiling", "critical_files_paths")
    )
    new_critical_paths_field = read_yaml_field(
        new_yaml, ("profiling", "critical_files_paths")
    )
    if new_critical_paths_field and not existing_critical_paths_field:
        track_manual_critical_file_labelling_added_in_YAML(
            repository.repoid, repository.ownerid, is_enterprise
        )
    if existing_critical_paths_field and not new_critical_paths_field:
        track_manual_critical_file_labelling_removed_from_YAML(
            repository.repoid, repository.ownerid, is_enterprise
        )
