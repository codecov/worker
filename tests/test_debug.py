import orjson
import pytest
from shared.reports.resources import Report
from shared.utils.sessions import Session

from services.report import raw_upload_processor as process
from services.report.parser.legacy import LegacyReportParser

# The intention of these tests is to easily reproduce production problems with real reports.
#
# In order to run them, comment out the `skip` annotation.
#
# For both tests, download the raw upload, or the `report_json`/`chunks` from storage,
# and paste in the filename before running the test directly.
#
# As these tests do not depend on any external service, you can run them directly with:
# > pytest -vvs "tests/test_debug.py::test_process_upload"
#
# Then either hook up an interactive debugger, or do "print-debugging" to your liking.


@pytest.mark.skip(reason="this is supposed to be invoked manually")
def test_process_upload():
    upload_file = "..."
    with open(upload_file, "rb") as d:
        contents = d.read()

    parsed_upload = LegacyReportParser().parse_raw_report_from_bytes(contents)
    report = process.process_raw_upload(None, parsed_upload, Session())

    file = report.get("interesting_file")


@pytest.mark.skip(reason="this is supposed to be invoked manually")
def test_inspect_report():
    report_json_file = "..."
    chunks_file = "..."
    with open(report_json_file, "rb") as d:
        report_json = d.read()
    with open(chunks_file, "rb") as d:
        chunks = d.read()

    report_json = orjson.loads(report_json)
    report = Report.from_chunks(
        chunks=chunks,
        files=report_json["files"],
        sessions=report_json["sessions"],
        totals=report_json.get("totals"),
    )

    file = report.get("interesting_file")
