import datetime
import xml.etree.cElementTree as etree
from time import time

import pytest

from helpers.exceptions import ReportExpiredException
from services.report.languages import clover
from services.report.report_builder import ReportBuilder
from test_utils.base import BaseTestCase

xml = """<?xml version="1.0" encoding="UTF-8"?>
<coverage generated="%s">
  <project timestamp="1410539625">
    <package name="Codecov">
      <file name="source.php">
        <class name="Coverage" namespace="Codecov">
          <metrics methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="6" coveredstatements="2" elements="7" coveredelements="2"/>
        </class>
        <line num="5" type="method" name="send" crap="125.96" count="1"/>
        <line complexity="9" visibility="private" signature="findRepeatableAnnotations(AnnotatedElement,Class&lt;A&gt;,Set&lt;Annotation&gt;) : List&lt;A&gt;" num="6" count="2969" type="method"/>

        <line falsecount="0" truecount="1" num="1" type="cond"/>
        <line falsecount="1" truecount="0" num="2" type="cond"/>
        <line falsecount="1" truecount="1" num="3" type="cond"/>
        <line falsecount="0" truecount="0" num="4" type="cond"/>

        <line num="8" type="stmt" count="0"/>
        <line num="11" type="stmt" count="1"/>
        <line num="21" type="stmt" count="0"/>
        <line num="22" type="stmt" count="0"/>
        <line num="23" type="stmt" count="0"/>
        <line num="87" type="stmt" count="0"/>
        <metrics loc="86" ncloc="62" classes="1" methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="6" coveredstatements="2" elements="7" coveredelements="2"/>
      </file>
      <file path="file.php">
        <class name="Coverage" namespace="Codecov">
          <metrics methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="0" coveredstatements="0" elements="0" coveredelements="0"/>
        </class>
        <line num="11" type="stmt" count="1"/>
      </file>
      <file name="nolines">
        <class name="Coverage" namespace="Codecov">
          <metrics methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="0" coveredstatements="0" elements="0" coveredelements="0"/>
        </class>
      </file>
      <file name="ignore">
        <class name="Coverage" namespace="Codecov">
          <metrics methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="0" coveredstatements="0" elements="0" coveredelements="0"/>
        </class>
        <line num="11" type="stmt" count="1"/>
      </file>
      <file name="vendor/ignoreme.php">
        <class name="Coverage" namespace="Codecov">
          <metrics methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="0" coveredstatements="0" elements="0" coveredelements="0"/>
        </class>
      </file>
      <file name="/${1}.php">
        <class name="Coverage" namespace="Codecov">
          <metrics methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="0" coveredstatements="0" elements="0" coveredelements="0"/>
        </class>
      </file>
    </package>
    <metrics files="1" loc="86" ncloc="62" classes="1" methods="1" coveredmethods="0" conditionals="0" coveredconditionals="0" statements="6" coveredstatements="2" elements="7" coveredelements="2"/>
  </project>
</coverage>
"""

result = {
    "files": {
        "file.php": {"l": {"11": {"c": 1, "s": [[0, 1, None, None, None]]}}},
        "source.php": {
            "l": {
                "11": {"c": 1, "s": [[0, 1, None, None, None]]},
                "21": {"c": 0, "s": [[0, 0, None, None, None]]},
                "22": {"c": 0, "s": [[0, 0, None, None, None]]},
                "23": {"c": 0, "s": [[0, 0, None, None, None]]},
                "5": {"c": 1, "s": [[0, 1, None, None, 0]], "t": "m"},
                "6": {"c": 2969, "C": 9, "s": [[0, 2969, None, None, 9]], "t": "m"},
                "1": {"c": "1/2", "s": [[0, "1/2", None, None, None]], "t": "b"},
                "2": {"c": "1/2", "s": [[0, "1/2", None, None, None]], "t": "b"},
                "3": {"c": "2/2", "s": [[0, "2/2", None, None, None]], "t": "b"},
                "4": {"c": "0/2", "s": [[0, "0/2", None, None, None]], "t": "b"},
                "8": {"c": 0, "s": [[0, 0, None, None, None]]},
            }
        },
    }
}


class TestCloverProcessor(BaseTestCase):
    def test_report(self):
        def fixes(path):
            if path == "ignore":
                return None
            assert path in ("source.php", "file.php", "nolines")
            return path

        report_builder = ReportBuilder(
            path_fixer=fixes, ignored_lines={}, sessionid=0, current_yaml=None
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = clover.from_xml(
            etree.fromstring(xml % int(time())), report_builder_session
        )
        processed_report = self.convert_report_to_better_readable(report)
        expected_result = {
            "archive": {
                "file.php": [(11, 1, None, [[0, 1, None, None, None]], None, None)],
                "source.php": [
                    (1, "1/2", "b", [[0, "1/2", None, None, None]], None, None),
                    (2, "1/2", "b", [[0, "1/2", None, None, None]], None, None),
                    (3, "2/2", "b", [[0, "2/2", None, None, None]], None, None),
                    (4, "0/2", "b", [[0, "0/2", None, None, None]], None, None),
                    (5, 1, "m", [[0, 1, None, None, 0]], None, 0),
                    (6, 2969, "m", [[0, 2969, None, None, 9]], None, 9),
                    (8, 0, None, [[0, 0, None, None, None]], None, None),
                    (11, 1, None, [[0, 1, None, None, None]], None, None),
                    (21, 0, None, [[0, 0, None, None, None]], None, None),
                    (22, 0, None, [[0, 0, None, None, None]], None, None),
                    (23, 0, None, [[0, 0, None, None, None]], None, None),
                ],
            },
            "report": {
                "files": {
                    "file.php": [
                        1,
                        [0, 1, 1, 0, 0, "100", 0, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "source.php": [
                        0,
                        [0, 11, 4, 5, 2, "36.36364", 4, 2, 0, 0, 9, 0, 0],
                        None,
                        None,
                    ],
                },
                "sessions": {},
            },
            "totals": {
                "C": 9,
                "M": 0,
                "N": 0,
                "b": 4,
                "c": "41.66667",
                "d": 2,
                "diff": None,
                "f": 2,
                "h": 5,
                "m": 5,
                "n": 12,
                "p": 2,
                "s": 0,
            },
        }

        assert processed_report == expected_result

    @pytest.mark.parametrize(
        "date",
        [
            (datetime.datetime.now() - datetime.timedelta(seconds=172800))
            .replace(minute=0, second=0)
            .strftime("%s"),
            "01-01-2014",
        ],
    )
    def test_expired(self, date):
        with pytest.raises(ReportExpiredException, match="Clover report expired"):
            report_builder = ReportBuilder(
                path_fixer=str, ignored_lines={}, sessionid=0, current_yaml=None
            )
            report_builder_session = report_builder.create_report_builder_session(
                "filename"
            )
            clover.from_xml(etree.fromstring(xml % date), report_builder_session)
