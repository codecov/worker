import sentry_sdk

from database.models.reports import Upload
from services.report.parser.legacy import LegacyReportParser
from services.report.parser.version_one import VersionOneReportParser


def get_proper_parser(upload: Upload, contents: bytes):
    if upload.upload_extras and upload.upload_extras.get("format_version") == "v1":
        contents = contents.strip()
        if contents.startswith(b"{") and contents.endswith(b"}"):
            return VersionOneReportParser()
        else:
            with sentry_sdk.new_scope() as scope:
                scope.set_extra("upload_extras", upload.upload_extras)
                scope.set_extra("contents", contents[:64])
                sentry_sdk.capture_message("Upload `format_version` lied to us")
    return LegacyReportParser()
