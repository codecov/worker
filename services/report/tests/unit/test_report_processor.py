import pytest

from services.report.languages.helpers import remove_non_ascii
from services.report.parser.types import ParsedUploadedReportFile
from services.report.report_processor import process_report, report_type_matching

xcode_report = b"""/Users/distiller/project/Auth0/A0ChallengeGenerator.m:
   28|       |@implementation A0SHA256ChallengeGenerator
   29|       |
   30|      7|- (instancetype)init {
   31|      7|    NSMutableData *data = [NSMutableData dataWithLength:kVerifierSize];
   32|      7|    int result __attribute__((unused)) = SecRandomCopyBytes(kSecRandomDefault, kVerifierSize, data.mutableBytes);
"""


@pytest.mark.parametrize(
    "input,expected_type,expected_content",
    [
        (b"", "txt", b""),
        (b"{}", "json", {}),
        (xcode_report, "txt", None),
        (b'{"value":1}', "json", {"value": 1}),
        (
            b'<?xml version="1.0" ?><statements><statement>source.scala</statement></statements>',
            "xml",
            None,
        ),
        (
            b'\n\n\n\n\n<?xml version="1.0" ?><statements><statement>source.scala</statement></statements>',
            "xml",
            None,
        ),
        (
            # NOTE: The `\ufeff` is a BOM (byte-order-mark)
            '\ufeff<?xml version="1.0" ?><statements><statement>source.scala</statement></statements>'.encode(),
            "xml",
            None,
        ),
        (b"normal file", "txt", b"normal file"),
        (b"1", "txt", b"1"),
    ],
)
def test_report_type_matching(input: bytes, expected_type: str, expected_content):
    report = ParsedUploadedReportFile(filename="name", file_contents=input)
    first_line = remove_non_ascii(report.get_first_line().decode(errors="replace"))

    content, detected_type = report_type_matching(
        report,
        first_line,
    )
    assert detected_type == expected_type
    if expected_content is not None:
        assert content == expected_content


def test_empty_json():
    raw_report = ParsedUploadedReportFile(filename="name", file_contents=b"{}")
    report = process_report(raw_report, None)
    assert report is None

    raw_report = ParsedUploadedReportFile(filename="name", file_contents=b"[]")
    report = process_report(raw_report, None)
    assert report is None
