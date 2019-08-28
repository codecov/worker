from services.storage import get_appropriate_storage_service
from services.report import ReportService
from database.engine import get_db_session
from database.models import Commit


def find_filepaths_in_common(first_bucket, second_bucket):
    storage_service = get_appropriate_storage_service()
    minio_client = storage_service.minio_client # Its the same client
    first_folders = minio_client.list_objects_v2(first_bucket, prefix='v4/repos', recursive=True)
    second_folders = minio_client.list_objects_v2(second_bucket, prefix='v4/repos', recursive=True)
    set_1 = set(obj.object_name for obj in first_folders)
    set_2 = set(obj.object_name for obj in second_folders)
    final_set = set_1 & set_2
    report_service = ReportService()
    errors = []
    for fln in final_set:
        res = compare_buckets_contents(storage_service, report_service, first_bucket, second_bucket, fln)
        if not res:
            errors.append(fln)
    return errors


def commitid_from_path(path):
    return path.split("/commits/")[1].split("/chunks")[0]


def compare_buckets_contents(storage_service, report_service, first_bucket, second_bucket, filename):
    commitid = commitid_from_path(filename)
    commit = db_session.query(Commit).filter_by(commitid=commitid).first()
    first_object_chunks = storage_service.read_file(first_bucket, filename).decode()
    second_object_chunks = storage_service.read_file(second_bucket, filename).decode()
    if first_object_chunks is None or second_object_chunks is None:
        return None
    if commit.report is None:
        return None
    files = commit.report['files']
    sessions = commit.report['sessions']
    totals = commit.totals
    first_report = report_service.build_report(first_object_chunks, files, sessions, totals)
    second_report = report_service.build_report(second_object_chunks, files, sessions, totals)
    if not compare_reports(first_report, second_report):
        print(f"ERROR ON {filename}")
        return False
    else:
        print(f"ok - {filename}")
        return True


def compare_reports(first_report, second_report):
    first_to_tuple = dict(first_report.network)
    second_to_tuple = dict(first_report.network)
    if set(first_to_tuple.keys()) != set(second_to_tuple.keys()):
        print("ERROR ON FILENAMES")
        return False
    for filename in first_to_tuple:
        f_c_1 = first_to_tuple[filename]
        f_c_2 = second_to_tuple[filename]
        if f_c_1 != f_c_2:
            print(f"ERROR ON FILENAME {filename}")
            return False
    return True


first_bucket = 'archive'
second_bucket = 'testingarchive03'
db_session = get_db_session()
errors = find_filepaths_in_common(first_bucket, second_bucket)
print(f"{len(errors)} found")
if errors:
    for err in errors:
        print(f"Error on f{err}")
