from database.models.reports import Upload
from services.report.parser.legacy import LegacyReportParser
from services.report.parser.version_one import VersionOneReportParser


def get_proper_parser(upload: Upload, use_legacy=None):
    if use_legacy:
        return LegacyReportParser()
    if upload.upload_extras and upload.upload_extras.get("format_version") == "v1":
        return VersionOneReportParser()
    return LegacyReportParser()
