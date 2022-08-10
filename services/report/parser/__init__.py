from database.models.reports import Upload
from services.report.parser.legacy import RawReportParser
from services.report.parser.version_one import NewReportParser


def get_proper_parser(upload: Upload):
    if upload.upload_extras and upload.upload_extras.get("format_version") == "v1":
        return NewReportParser()
    return RawReportParser()
