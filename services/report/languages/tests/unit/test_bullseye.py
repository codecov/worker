import time

import pytest
from lxml import etree

from helpers.exceptions import ReportExpiredException
from services.report.languages import bullseye
from services.report.report_builder import ReportBuilder
from test_utils.base import BaseTestCase

xml = """<?xml version="1.0" encoding="UTF-8"?>
<!-- BullseyeCoverage XML 8.23.15 Windows x64 -->
<BullseyeCoverage name="test.cov" dir="c:/project/cov/sample/" buildId="1234_%s" version="6" xmlns="https://www.bullseye.com/covxml" fn_cov="29" fn_total="29" cd_cov="108" cd_total="161" d_cov="107" d_total="153">
    <folder name="calc" fn_cov="10" fn_total="10" cd_cov="21" cd_total="50" d_cov="21" d_total="50">
        <src name="CalcCore.cpp" mtime="1603906269" fn_cov="7" fn_total="7" cd_cov="11" cd_total="17" d_cov="11" d_total="17">
            <fn name="CalcCore::unitTest()" fn_cov="1" fn_total="1" cd_cov="0" cd_total="0" d_cov="0" d_total="0">
                <probe line="11" column="4" kind="function" event="full" />
                <block line="12" entered="1" />
            </fn>
            <fn name="CalcCore::addNumberChar(char)" fn_cov="1" fn_total="1" cd_cov="0" cd_total="0" d_cov="0" d_total="0">
                <probe line="40" column="4" kind="function" event="true" />
                <block line="41" entered="1" />
            </fn>
            <fn name="CalcCore::apply()" fn_cov="1" fn_total="1" cd_cov="2" cd_total="2" d_cov="2" d_total="2">
                <probe line="47" column="4" kind="function" event="full" />
                <probe line="49" kind="decision" event="full" />
                <block line="48" entered="1" />
                <block line="50" entered="1" />
            </fn>
            <fn name="CalcCore::apply(Operation)" fn_cov="1" fn_total="1" cd_cov="4" cd_total="6" d_cov="4" d_total="6">
                <probe line="57" column="4" kind="function" event="full" />
                <probe line="60" kind="switch-label" event="none" />
                <probe line="63" kind="switch-label" event="none" />
                <probe line="66" kind="switch-label" event="full" />
                <probe line="69" kind="switch-label" event="full" />
                <probe line="70" kind="decision" event="full" />
                <block line="58" entered="1" />
                <block line="61" entered="0" />
                <block line="64" entered="0" />
                <block line="67" entered="1" />
                <block line="70" entered="1" />
                <block line="71" entered="1" />
            </fn>
        </src>
        <src name="CalcCore.h" mtime="1603846879" fn_cov="1" fn_total="1" cd_cov="0" cd_total="0" d_cov="0" d_total="0">
            <fn name="CalcCore::addNumber(double)" fn_cov="1" fn_total="1" cd_cov="0" cd_total="0" d_cov="0" d_total="0">
                <probe line="15" column="4" kind="function" event="full" />
                <block line="15" entered="1" />
            </fn>
        </src>
        <src name="Calculator.cpp" mtime="1603932332" fn_cov="2" fn_total="2" cd_cov="10" cd_total="33" d_cov="10" d_total="33">
            <fn name="wWinMain(HINSTANCE,HINSTANCE,PWSTR,int)" fn_cov="1" fn_total="1" cd_cov="3" cd_total="4" d_cov="3" d_total="4">
                <probe line="100" column="9" kind="function" event="full" />
                <probe line="122" kind="decision" event="full" />
                <probe line="125" kind="try" event="full" />
                <probe line="126" column="23" kind="catch" event="none" />
                <block line="101" entered="1" />
                <block line="123" entered="1" />
                <block line="127" entered="0" />
            </fn>
        </src>
    </folder>
</BullseyeCoverage>
"""

expected_result = {
    "archive": {
        "calc/CalcCore.cpp": [
            (11, 1, "m", [[0, 1, None, None, None]], None, None),
            (40, "1/2", "m", [[0, "1/2", None, None, None]], None, None),
            (47, 1, "m", [[0, 1, None, None, None]], None, None),
            (49, 1, "b", [[0, 1, None, None, None]], None, None),
            (57, 1, "m", [[0, 1, None, None, None]], None, None),
            (60, 0, "b", [[0, 0, None, None, None]], None, None),
            (63, 0, "b", [[0, 0, None, None, None]], None, None),
            (66, 1, "b", [[0, 1, None, None, None]], None, None),
            (69, 1, "b", [[0, 1, None, None, None]], None, None),
            (70, 1, "b", [[0, 1, None, None, None]], None, None),
        ],
        "calc/CalcCore.h": [(15, 1, "m", [[0, 1, None, None, None]], None, None)],
        "calc/Calculator.cpp": [
            (100, 1, "m", [[0, 1, None, None, None]], None, None),
            (122, 1, "b", [[0, 1, None, None, None]], None, None),
            (125, 1, None, [[0, 1, None, None, None]], None, None),
            (126, 0, None, [[0, 0, None, None, None]], None, None),
        ],
    },
    "report": {
        "files": {
            "calc/CalcCore.cpp": [
                0,
                [0, 10, 7, 2, 1, "70.00000", 6, 4, 0, 0, 0, 0, 0],
                None,
                None,
            ],
            "calc/CalcCore.h": [
                1,
                [0, 1, 1, 0, 0, "100", 0, 1, 0, 0, 0, 0, 0],
                None,
                None,
            ],
            "calc/Calculator.cpp": [
                2,
                [0, 4, 3, 1, 0, "75.00000", 1, 1, 0, 0, 0, 0, 0],
                None,
                None,
            ],
        },
        "sessions": {},
    },
    "totals": {
        "f": 3,
        "n": 15,
        "h": 11,
        "m": 3,
        "p": 1,
        "c": "73.33333",
        "b": 7,
        "d": 6,
        "M": 0,
        "s": 0,
        "C": 0,
        "N": 0,
        "diff": None,
    },
}


class TestBullseye(BaseTestCase):
    def test_report(self):
        def fixes(path):
            if path == "ignore":
                return None
            assert path in (
                "calc/CalcCore.cpp",
                "calc/CalcCore.h",
                "calc/Calculator.cpp",
            )
            return path

        date = time.strftime("%Y-%m-%d_%H:%M:%S", (time.gmtime(time.time())))
        report_builder = ReportBuilder(
            path_fixer=fixes, ignored_lines={}, sessionid=0, current_yaml=None
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = bullseye.from_xml(
            etree.fromstring((xml % date).encode(), None), report_builder_session
        )
        processed_report = self.convert_report_to_better_readable(report)
        assert processed_report == expected_result

    @pytest.mark.parametrize(
        "date",
        [
            (time.strftime("%Y-%m-%d_%H:00:00", (time.gmtime(time.time() - 172800)))),
            "2020-10-28_17:55:47",
        ],
    )
    def test_expired(self, date):
        report_builder = ReportBuilder(
            path_fixer=str, ignored_lines={}, sessionid=0, current_yaml=None
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        with pytest.raises(ReportExpiredException, match="Bullseye report expired"):
            bullseye.from_xml(
                etree.fromstring((xml % date).encode(), None), report_builder_session
            )

    def test_matches_content(self):
        processor = bullseye.BullseyeProcessor()
        content = etree.fromstring(
            (xml % time.strftime("%Y-%m-%d_%H:%M:%S")).encode(), None
        )
        first_line = xml.split("\n", 1)[0]
        name = "coverage.xml"
        assert processor.matches_content(content, first_line, name)
