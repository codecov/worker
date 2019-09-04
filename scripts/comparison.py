import requests

from services.storage import get_appropriate_storage_service
from services.report import ReportService
from database.engine import get_db_session
from database.models import Commit


def commitid_from_path(path):
    return path.split("/commits/")[1].split("/chunks")[0]


def compare_buckets_contents(storage_service, report_service, old_bucket, new_bucket, filename):
    commitid = commitid_from_path(filename)
    commit = db_session.query(Commit).filter_by(commitid=commitid).first()
    old_object_chunks = requests.get(f"https://codecov.io/archive/{filename}").content.decode()
    new_object_chunks = storage_service.read_file(new_bucket, filename).decode()
    if old_object_chunks is None or new_object_chunks is None:
        return None
    if commit.report is None:
        return None
    files = commit.report['files']
    sessions = commit.report['sessions']
    old_report = report_service.build_report(old_object_chunks, files, sessions, totals=None)
    new_report = report_service.build_report(new_object_chunks, files, sessions, totals=None)
    return old_report, new_report


old_bucket = 'archive'
new_bucket = 'testingarchive03'
db_session = get_db_session()
storage_service = get_appropriate_storage_service()
report_service = ReportService()
filename = 'v4/repos/70F18DD5B2D477D3C932F6935B306126/commits/63b9198f970b15c144fbdd949b6c1c259c630658/chunks.txt'
old_report, new_report = compare_buckets_contents(
    storage_service, report_service, old_bucket, new_bucket, filename
)
to_check = 'Log.cpp'
old_file = old_report.get(to_check)
new_file = new_report.get(to_check)
print(old_file.totals)
print(new_file.totals)
for number, res in enumerate(zip(old_file._lines, new_file._lines), start=1):
    old, new = res
    if old != new:
        print(number)
        print(old)
        print(new)
