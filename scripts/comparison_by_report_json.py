import json
from datetime import datetime, timedelta
from collections import Counter
import pprint

import pytz


from services.storage import get_appropriate_storage_service
from database.engine import get_db_session
from database.models import Commit


def find_filepaths_in_common(test_bucket, db_session):
    storage_service = get_appropriate_storage_service()
    minio_client = storage_service.minio_client
    first_folders = minio_client.list_objects_v2(test_bucket, prefix='v4/repos', recursive=True)
    results = []
    for fln in first_folders:
        if 'report.json' in fln.object_name and fln.last_modified > since:
            content = storage_service.read_file(test_bucket, fln.object_name).decode()
            result = compare_report_contents(db_session, content, fln.object_name)
            print(f"{result['case']:>30} - {result['repo']:>7}/{result['commit']}")
            results.append(result)
    return results


def commitid_from_path(path):
    return path.split("/commits/")[1].split("/report")[0]


def compare_report_contents(db_session, compare_report_contents, filename):
    commitid = commitid_from_path(filename)
    commit = db_session.query(Commit).filter_by(commitid=commitid).first()
    json_content = json.loads(compare_report_contents)
    if commit.report is None:
        return {
            'error': False,
            'commit': commit.commitid,
            'repo': commit.repoid,
            'case': 'production_without_report',
        }
    files = commit.report['files']
    if len(commit.report['sessions']) != len(json_content['sessions']):
        return {
            'error': False,
            'commit': commit.commitid,
            'repo': commit.repoid,
            'case': 'difference_not_comparable',
            'old_number_sessions': len(commit.report['sessions']),
            'new_number_sessions':  len(json_content['sessions'])
        }
    if set(files.keys()) != set(json_content['files'].keys()):
        only_old = set(files.keys()) - set(json_content['files'].keys())
        only_new = set(json_content['files'].keys()) - set(files.keys())
        return {
            'error': True,
            'case': 'number_files_mismatch',
            'commit': commit.commitid,
            'repo': commit.repoid,
            'only_on_old': only_old,
            'only_on_new': only_new
        }
    for inside_fln in files:
        old_result = files.get(inside_fln)
        new_result = json_content['files'].get(inside_fln)
        res = compare_individual_file(old_result, new_result)
        if not res:
            rounding_res = compare_individual_file_considering_rounding(old_result, new_result)
            if not rounding_res:
                return {
                    'error': True,
                    'case': 'actual_difference_error',
                    'commit': commit.commitid,
                    'repo': commit.repoid,
                    'old_result': old_result[1],
                    'new_result': new_result[1]
                }
            return {
                'error': False,
                'case': 'new_rounding_difference',
                'commit': commit.commitid,
                'repo': commit.repoid,
                'old_result': old_result[1],
                'new_result': new_result[1]
            }
    return {
        'error': False,
        'case': 'all_matches',
        'commit': commit.commitid,
        'repo': commit.repoid,
    }


def compare_individual_file(old_result, new_result):
    _, old_res, sess_old, _ = old_result
    _, new_res, sess_new, _ = new_result
    return old_res == new_res


def compare_individual_file_considering_rounding(old_result, new_result):
    _, old_res, sess_old, _ = old_result
    _, new_res, sess_new, _ = new_result
    return old_res[:5] == new_res[:5] and old_res[6:] == new_res[6:]


def run_test():
    test_bucket = 'testingarchive03'
    db_session = get_db_session()
    results = find_filepaths_in_common(test_bucket, db_session)
    counter = Counter(x['case'] for x in results)
    print(counter)
    db_session.close()
    return results


since = datetime.utcnow().replace(tzinfo=pytz.utc) - timedelta(hours=12)
print("Checking since", since)
results = run_test()
for x in results:
    if x['error']:
        pprint.pprint(x)
