import json
from io import BytesIO

from services.report.parser import ParsedUploadedReportFile
from services.report.report_processor import report_type_matching

xcode_report = """/Users/distiller/project/Auth0/A0ChallengeGenerator.m:
   28|       |@implementation A0SHA256ChallengeGenerator
   29|       |
   30|      7|- (instancetype)init {
   31|      7|    NSMutableData *data = [NSMutableData dataWithLength:kVerifierSize];
   32|      7|    int result __attribute__((unused)) = SecRandomCopyBytes(kSecRandomDefault, kVerifierSize, data.mutableBytes);
"""


class TestReportTypeMatching(object):
    def test_report_type_matching(self):
        assert (
            report_type_matching(
                ParsedUploadedReportFile(filename="name", file_contents=BytesIO(b""))
            )[1]
            == "txt"
        )
        assert (
            report_type_matching(
                ParsedUploadedReportFile(filename="name", file_contents=BytesIO(b"{}"))
            )[1]
            == "txt"
        )
        assert (
            report_type_matching(
                ParsedUploadedReportFile(
                    filename="name", file_contents=BytesIO(xcode_report.encode())
                )
            )[1]
            == "txt"
        )
        assert (
            report_type_matching(
                ParsedUploadedReportFile(
                    filename="name",
                    file_contents=BytesIO(json.dumps({"value": 1}).encode()),
                )
            )[1]
            == "json"
        )
        assert (
            report_type_matching(
                ParsedUploadedReportFile(
                    filename="name",
                    file_contents=BytesIO(
                        '<?xml version="1.0" ?><statements><statement>source.scala</statement></statements>'.encode()
                    ),
                )
            )[1]
            == "xml"
        )
        assert (
            report_type_matching(
                ParsedUploadedReportFile(
                    filename="name",
                    file_contents=BytesIO(
                        '\uFEFF<?xml version="1.0" ?><statements><statement>source.scala</statement></statements>'.encode()
                    ),
                )
            )[1]
            == "xml"
        )
        assert report_type_matching(
            ParsedUploadedReportFile(
                filename="name", file_contents=BytesIO("normal file".encode())
            )
        ) == (b"normal file", "txt")
        assert report_type_matching(
            ParsedUploadedReportFile(
                filename="name", file_contents=BytesIO("1".encode())
            )
        ) == (b"1", "txt")
