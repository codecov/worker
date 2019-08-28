import json
import pprint

from services.storage import get_appropriate_storage_service
from services.report import ReportService
from database.engine import get_db_session
from database.models import Commit


class FileDifferenceWeirdError(Exception):
    pass


def find_filepaths_in_common(test_bucket):
    storage_service = get_appropriate_storage_service()
    minio_client = storage_service.minio_client
    first_folders = minio_client.list_objects_v2(test_bucket, prefix='v4/repos', recursive=True)
    report_service = ReportService()
    errors = []
    successes = 0
    for fln in first_folders:
        if 'report.json' in fln.object_name:
            content = storage_service.read_file(test_bucket, fln.object_name).decode()
            try:
                compare_report_contents(storage_service, report_service, content, fln.object_name)
                successes += 1
            except FileDifferenceWeirdError as er:
                errors.append((fln.object_name, er.args))
    print(f"{successes} successes")
    return errors


def commitid_from_path(path):
    return path.split("/commits/")[1].split("/report")[0]


def compare_report_contents(storage_service, report_service, compare_report_contents, filename):
    commitid = commitid_from_path(filename)
    commit = db_session.query(Commit).filter_by(commitid=commitid).first()
    json_content = json.loads(compare_report_contents)
    files = commit.report['files']
    if set(files.keys()) != set(json_content['files'].keys()):
        only_old = set(files.keys()) - set(json_content['files'].keys())
        only_new = set(json_content['files'].keys()) - set(files.keys())
        raise FileDifferenceWeirdError(
            commit.repoid, commit.commitid, f"ERROR ON {filename} - {only_old} - {only_new}"
        )
    else:
        for inside_fln in files:
            res = compare_individual_file(files.get(inside_fln), json_content['files'].get(inside_fln))
            if not res:
                raise FileDifferenceWeirdError(
                    commit.repoid, commit.commitid, f"ERROR ON {filename} - Different value on {inside_fln}"
                )
    print(f"ok - {filename}")


def compare_individual_file(old_result, new_result):
    _, old_res, _, _ = old_result
    _, new_res, _, _ = new_result
    return old_res == new_res


test_bucket = 'testingarchive03'
db_session = get_db_session()
errors = find_filepaths_in_common(test_bucket)
print(f"{len(errors)} errors found")
if errors:
    for err in errors:
        print(f"Error on f{err}")

db_session.close()
