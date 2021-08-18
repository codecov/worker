from json import dumps

from services.report.languages import lcov
from tests.base import BaseTestCase

txt = b"""TN:
SF:file.js
FNDA:76,jsx
FN:76,(anonymous_1)
removed
DA:0,skipped
DA:null,skipped
DA:1,1
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
FNDA:1,_ln1_is_skipped
FNDA:,not_hit
FNDA:2,ignored
FNDA:3,ignored
FNDA:4,ignored
DA:1,1
DA:77,0
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

result = {
    "files": {
        "file.js": {"l": {"1": {"c": 1, "s": [[0, 1, None, None, None]]}}},
        "file.ts": {"l": {"2": {"c": 1, "s": [[0, 1, None, None, None]]}}},
        "file.cpp": {
            "l": {
                "1": {"c": 1, "s": [[0, 1, None, None, None]]},
                "5": {"c": "2/2", "t": "b", "s": [[0, "2/2", None, None, None]]},
                "2": {
                    "c": "1/3",
                    "t": "m",
                    "s": [[0, "1/3", ["1:1", "1:3"], None, None]],
                },
                "77": {
                    "c": "0/4",
                    "t": "b",
                    "s": [[0, "0/4", ["4:1", "4:0", "3:0", "3:1"], None, None]],
                },
            }
        },
    }
}


class TestLcov(BaseTestCase):
    def test_report(self):
        def fixes(path):
            if path == "ignore":
                return None
            assert path in ("file.js", "file.ts", "file.cpp", "empty.js")
            return path

        report = lcov.from_txt(txt, fixes, {}, 0)
        processed_report = self.convert_report_to_better_readable(report)
        import pprint

        pprint.pprint(processed_report["archive"])
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
                )
                # TODO (Thiago): This is out f order compared to the original, verify what happened
            ],
            "file.js": [(1, 1, None, [[0, 1, None, None, None]], None, None)],
            "file.ts": [(2, 1, None, [[0, 1, None, None, None]], None, None)],
        }

        assert expected_result_archive == processed_report["archive"]

    def test_detect(self):
        assert lcov.detect(b"hello\nend_of_record\n") is True
        assert lcov.detect(txt) is True
        assert lcov.detect(b"hello_end_of_record") is False
        assert lcov.detect(b"") is False

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
        report = lcov.from_txt(text, lambda x: x, {}, 0)
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
