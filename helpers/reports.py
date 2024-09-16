from collections import namedtuple

from shared.config import get_config
from shared.yaml import UserYaml

from services.yaml.reader import read_yaml_field

null = namedtuple("_", ["totals"])(None)


def get_totals_from_file_in_reports(report, path):
    return report.get(path, null).totals


def delete_archive_setting(commit_yaml: UserYaml | dict) -> bool:
    if get_config("services", "minio", "expire_raw_after_n_days"):
        return True
    return not read_yaml_field(
        commit_yaml, ("codecov", "archive", "uploads"), _else=True
    )
