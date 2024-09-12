from services.report.languages import lcov
from test_utils.base import BaseTestCase

from . import create_report_builder_session

txt = b"""TN:
SF:file.js
FNDA:76,jsx
FN:76,(anonymous_1)
removed
DA:0,skipped
DA:null,skipped
DA:1,1,46ba21aa66ea047aced7130c2760d7d4
DA:=,=
BRDA:0,1,0,1
BRDA:0,1,0,1
BRDA:1,1,0,1
BRDA:1,1,1,1
end_of_record

TN:
SF:empty.js
FNF:0
FNH:0
DA:0,1
LF:1
LH:1
BRF:0
BRH:0
end_of_record

TN:
SF:file.ts
FNF:0
FNH:0
DA:2,1
LF:1
LH:1
BRF:0
BRH:0
BRDA:1,1,0,1
end_of_record

TN:
SF:file.js
FNDA:76,jsx
FN:76,(anonymous_1)
removed
DA:0,skipped
DA:null,skipped
DA:1,0
DA:=,=
DA:2,1e+0
BRDA:0,0,0,0
BRDA:1,1,1,1
end_of_record

TN:
SF:ignore
end_of_record

TN:
SF:file.cpp
FN:2,not_hit
FN:3,_Zalkfjeo
FN:4,_Gsabebra
FN:78,_Zalkfjeo2
FNDA:1,_ln1_is_skipped
FNDA:,not_hit
FNDA:2,ignored
FNDA:3,ignored
FNDA:4,ignored
FNDA:78,1+e0
DA:1,1
DA:77,0
DA:78,1
BRDA:2,1,0,1
BRDA:2,1,1,-
BRDA:2,1,3,0
BRDA:5,1,0,1
BRDA:5,1,1,1
BRDA:77,3,0,0
BRDA:77,3,1,0
BRDA:77,4,0,0
BRDA:77,4,1,0
end_of_record
"""


class TestLcov(BaseTestCase):
    def test_report(self):
        def fixes(path):
            if path == "ignore":
                return None
            assert path in ("file.js", "file.ts", "file.cpp", "empty.js")
            return path

        report_builder_session = create_report_builder_session(path_fixer=fixes)
        lcov.from_txt(txt, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        expected_result_archive = {
            "file.cpp": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (2, "1/3", "m", [[0, "1/3", ["1:1", "1:3"], None, None]], None, None),
                (5, "2/2", "b", [[0, "2/2", None, None, None]], None, None),
                (
                    77,
                    "0/4",
                    "b",
                    [[0, "0/4", ["3:0", "3:1", "4:0", "4:1"], None, None]],
                    None,
                    None,
                ),
                (
                    78,
                    1,
                    None,
                    [[0, 1, None, None, None]],
                    None,
                    None,
                ),
                # TODO (Thiago): This is out of order compared to the original, verify what happened
            ],
            "file.js": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (2, 1, None, [[0, 1, None, None, None]], None, None),
            ],
            "file.ts": [(2, 1, None, [[0, 1, None, None, None]], None, None)],
        }

        assert expected_result_archive == processed_report["archive"]

    def test_detect(self):
        processor = lcov.LcovProcessor()
        assert processor.matches_content(b"hello\nend_of_record\n", "", "") is True
        assert processor.matches_content(txt, "", "") is True
        assert processor.matches_content(b"hello_end_of_record", "", "") is False
        assert processor.matches_content(b"", "", "") is False

    def test_negative_execution_count(self):
        text = "\n".join(
            [
                "TN:",
                "SF:file.js",
                "DA:1,1",
                "DA:2,2",
                "DA:3,0",
                "DA:4,-1",
                "DA:5,-5",
                "DA:6,-20",
                "end_of_record",
            ]
        ).encode()
        report_builder_session = create_report_builder_session()
        lcov.from_txt(text, report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        assert processed_report["archive"] == {
            "file.js": [
                (1, 1, None, [[0, 1, None, None, None]], None, None),
                (2, 2, None, [[0, 2, None, None, None]], None, None),
                (3, 0, None, [[0, 0, None, None, None]], None, None),
                (4, -1, None, [[0, -1, None, None, None]], None, None),
                (5, 0, None, [[0, 0, None, None, None]], None, None),
                (6, 0, None, [[0, 0, None, None, None]], None, None),
            ]
        }
