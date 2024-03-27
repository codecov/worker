from database.models.reports import Upload
from services.report.parser.legacy import LegacyReportParser
from services.report.parser.version_one import VersionOneReportParser


def get_proper_parser(upload: Upload, parallel_idx=None):
    if parallel_idx is not None:
        print("ARE WE USING THIS")
        return LegacyReportParser()
    print("WER'RE NOT USING THIS")
    if upload.upload_extras and upload.upload_extras.get("format_version") == "v1":
        return VersionOneReportParser()
    return LegacyReportParser()
