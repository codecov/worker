import json
from datetime import datetime, timedelta
import pytz
from services.storage import get_appropriate_storage_service
from database.engine import get_db_session
from database.models import Commit


class FileDifferenceWeirdError(Exception):
    pass


class FileDifferenceNotComparableCase(Exception):
    pass


def find_filepaths_in_common(test_bucket, db_session):
    storage_service = get_appropriate_storage_service()
    minio_client = storage_service.minio_client
    first_folders = minio_client.list_objects_v2(test_bucket, prefix='v4/repos', recursive=True)
    errors = []
    non_comparables = 0
    successes = 0
    for fln in first_folders:
        if 'report.json' in fln.object_name and fln.last_modified > since:
            content = storage_service.read_file(test_bucket, fln.object_name).decode()
            try:
                compare_report_contents(db_session, content, fln.object_name)
                successes += 1
            except FileDifferenceWeirdError as er:
                errors.append((fln.object_name, er.args))
            except FileDifferenceNotComparableCase:
                non_comparables += 1
    print(f"{successes} successes")
    print(f"{non_comparables} non_comparables")
    print(f"{len(errors)} errors")
    return errors


def commitid_from_path(path):
    return path.split("/commits/")[1].split("/report")[0]


def compare_report_contents(db_session, compare_report_contents, filename):
    commitid = commitid_from_path(filename)
    commit = db_session.query(Commit).filter_by(commitid=commitid).first()
    json_content = json.loads(compare_report_contents)
    files = commit.report['files']
    if len(commit.report['sessions']) != len(json_content['sessions']):
        print(f"not comparable - {filename}")
        raise FileDifferenceNotComparableCase(
            len(commit.report['sessions']), len(json_content['sessions'])
        )
    if set(files.keys()) != set(json_content['files'].keys()):
        only_old = set(files.keys()) - set(json_content['files'].keys())
        only_new = set(json_content['files'].keys()) - set(files.keys())
        raise FileDifferenceWeirdError(
            commit.repoid, commit.commitid, f"ERROR ON {filename} - {only_old} - {only_new}"
        )
    else:
        for inside_fln in files:
            old_result = files.get(inside_fln)
            new_result = json_content['files'].get(inside_fln)
            res = compare_individual_file(old_result, new_result)
            if not res:
                raise FileDifferenceWeirdError(
                    commit.repoid, commit.commitid,
                    f"ERROR ON {filename} - Different value on {inside_fln}", old_result[1], new_result[1]
                )
    print(f"ok - {filename}")


def compare_individual_file(old_result, new_result):
    _, old_res, sess_old, _ = old_result
    _, new_res, sess_new, _ = new_result
    return old_res == new_res


def run_test():
    test_bucket = 'testingarchive03'
    db_session = get_db_session()
    errors = find_filepaths_in_common(test_bucket, db_session)
    print(f"{len(errors)} errors found")
    if errors:
        for err in errors:
            print(f"Error on {err}")
    db_session.close()


since = datetime.utcnow().replace(tzinfo=pytz.utc) - timedelta(hours=6)
print("Checking since", since)
run_test()
