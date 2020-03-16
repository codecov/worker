import json

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
        assert report_type_matching("name", "")[1] == "txt"
        assert report_type_matching("name", "{}")[1] == "txt"
        assert report_type_matching("name", xcode_report)[1] == "txt"
        assert report_type_matching("name", json.dumps({"value": 1}))[1] == "json"
        assert (
            report_type_matching(
                "name",
                '<?xml version="1.0" ?><statements><statement>source.scala</statement></statements>',
            )[1]
            == "xml"
        )
        assert (
            report_type_matching(
                "name",
                '\uFEFF<?xml version="1.0" ?><statements><statement>source.scala</statement></statements>',
            )[1]
            == "xml"
        )
        assert report_type_matching("name", "normal file")[1] == "txt"
