from json import dumps

from tests.base import TestCase
from app.tasks.reports.languages import lcov


txt = '''TN:
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
'''

result = {
    "files": {
        "file.js": {
            "l": {
                "1": {"c": 1, "s": [[0, 1, None, None, None]]}
            }
        },
        "file.ts": {
            "l": {
                "2": {"c": 1, "s": [[0, 1, None, None, None]]}
            }
        },
        "file.cpp": {
            "l": {
                "1": {"c": 1, "s": [[0, 1, None, None, None]]},
                "5": {"c": "2/2", "t": "b", "s": [[0, "2/2", None, None, None]]},
                "2": {
                    "c": "1/3",
                    "t": "m",
                    "s": [[0, "1/3", ["1:1", "1:3"], None, None]]
                },
                "77": {
                    "c": "0/4",
                    "t": "b",
                    "s": [[0, "0/4", ["4:1", "4:0", "3:0", "3:1"], None, None]]
                }
            }
        }
    }
}


class Test(TestCase):
    def test_report(self):
        def fixes(path):
            if path == 'ignore':
                return None
            assert path in ('file.js', 'file.ts', 'file.cpp', 'empty.js')
            return path

        report = lcov.from_txt(txt, fixes, {}, 0)
        report = self.v3_to_v2(report)
        print dumps(report, indent=2)
        self.validate.report(report)
        assert result == report

    def test_detect(self):
        assert lcov.detect('hello\nend_of_record\n') is True
        assert lcov.detect('hello_end_of_record') is False
        assert lcov.detect('') is False
