import datetime
import os
import xml.etree.cElementTree as etree
from time import time

import pytest

from helpers.exceptions import ReportExpiredException
from services.path_fixer import PathFixer
from services.report.languages import cobertura
from services.report.report_builder import ReportBuilder
from test_utils.base import BaseTestCase

xml = """<?xml version="1.0" ?>
<!DOCTYPE coverage
  SYSTEM 'http://cobertura.sourceforge.net/xml/coverage-03.dtd'>
<%scoverage branch-rate="0.07143" line-rate="0.5506" timestamp="%s" version="3.7.1">
    %s
    <!-- Generated by coverage.py: http://nedbatchelder.com/code/coverage -->
    <packages>
        <package branch-rate="0.07143" complexity="0" line-rate="0.5506" name="">
            <classes>
                <class branch-rate="0.07143" complexity="0" filename="empty" line-rate="0.5506" name="empty/src"></class>
                <class branch-rate="0.07143" complexity="0" filename="source" line-rate="0.5506" name="folder/file">
                    <methods>
                        <method name="(anonymous_1)"  hits="1"  signature="()V" >
                            <lines><line number="undefined"  hits="1" /></lines>
                        </method>
                    </methods>
                    <lines>
                        <line hits="8" number="0"/>
                        <line hits="1.0" number="1"/>
                        <line branch="true" condition-coverage="0%% (0/2)" hits="1" missing-branches="exit" number="2"/>
                        <line branch="true" condition-coverage="50%% (1/2)" hits="1" missing-branches="30" number="3"/>
                        <line branch="true" condition-coverage="100%% (2/2)" hits="1" number="4"/>
                        <line number="5" hits="0" branch="true" condition-coverage="50%% (2/4)">
                          <conditions>
                            <condition number="0" type="jump" coverage="0%%"/>
                            <condition number="1" type="jump" coverage="0%%"/>
                            <condition number="2" type="jump" coverage="100%%"/>
                            <condition number="3" type="jump" coverage="100%%"/>
                          </conditions>
                        </line>
                        <line number="6" hits="0" branch="true" condition-coverage="50%% (2/4)">
                          <conditions>
                            <condition number="0" type="jump" coverage="0%%"/>
                            <condition number="1" type="jump" coverage="0%%"/>
                          </conditions>
                        </line>
                        <line branch="true" condition-coverage="0%% (0/2)" hits="1" missing-branches="exit,exit,exit" number="7"/>
                        <line branch="true" condition-coverage="50%%" hits="1" number="8"/>
                        <line number="9" hits="0" branch="true" condition-coverage="50%% (1/2)"/>
                    </lines>
                </class>
                <!-- Scala coverage -->
                <class branch-rate="0.07143" complexity="0" filename="file" line-rate="0.5506" name="">
                    <methods>
                        <statements>
                            <statement source="file" method="beforeInteropCommit" line="1" branch="false" invocation-count="0"></statement>
                            <statement source="file" method="" line="2" branch="true" invocation-count="1"></statement>
                            <statement source="file" method="" line="3" branch="false" invocation-count="1"></statement>
                        </statements>
                    </methods>
                </class>
                <class branch-rate="0.07143" complexity="0" filename="ignore" line-rate="0.5506" name="codecov/__init__"></class>
            </classes>
        </package>
    </packages>
</%scoverage>
"""


class TestCobertura(BaseTestCase):
    def test_report(self):
        def fixes(path, *, bases_to_try):
            if path == "ignore":
                return None
            assert path in ("source", "empty", "file", "nolines")
            return path

        report_builder = ReportBuilder(
            path_fixer=fixes,
            ignored_lines={},
            sessionid=0,
            current_yaml={"codecov": {"max_report_age": None}},
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = cobertura.from_xml(
            etree.fromstring(xml % ("", int(time()), "", "")), report_builder_session
        )
        processed_report = self.convert_report_to_better_readable(report)
        import pprint

        pprint.pprint(processed_report)
        expected_result = {
            "archive": {
                "file": [
                    (1, 0, "m", [[0, 0, None, None, None]], None, None),
                    (2, 1, "b", [[0, 1, None, None, None]], None, None),
                    (3, 1, None, [[0, 1, None, None, None]], None, None),
                ],
                "source": [
                    (1, 1, None, [[0, 1, None, None, None]], None, None),
                    (2, "0/2", "b", [[0, "0/2", ["exit"], None, None]], None, None),
                    (3, "1/2", "b", [[0, "1/2", ["30"], None, None]], None, None),
                    (4, "2/2", "b", [[0, "2/2", None, None, None]], None, None),
                    (
                        5,
                        "2/4",
                        "b",
                        [[0, "2/4", ["0:jump", "1:jump"], None, None]],
                        None,
                        None,
                    ),
                    (
                        6,
                        "2/4",
                        "b",
                        [[0, "2/4", ["0:jump", "1:jump"], None, None]],
                        None,
                        None,
                    ),
                    (
                        7,
                        "0/2",
                        "b",
                        [[0, "0/2", ["loop", "exit"], None, None]],
                        None,
                        None,
                    ),
                    (8, 1, None, [[0, 1, None, None, None]], None, None),
                    (9, "1/2", "b", [[0, "1/2", None, None, None]], None, None),
                ],
            },
            "report": {
                "files": {
                    "file": [
                        1,
                        [0, 3, 2, 1, 0, "66.66667", 1, 1, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "source": [
                        0,
                        [0, 9, 3, 2, 4, "33.33333", 7, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                },
                "sessions": {},
            },
            "totals": {
                "C": 0,
                "M": 0,
                "N": 0,
                "b": 8,
                "c": "41.66667",
                "d": 1,
                "diff": None,
                "f": 2,
                "h": 5,
                "m": 3,
                "n": 12,
                "p": 4,
                "s": 0,
            },
        }
        assert processed_report["archive"] == expected_result["archive"]
        assert processed_report["report"] == expected_result["report"]
        assert processed_report["totals"] == expected_result["totals"]
        assert processed_report == expected_result

    def test_report_missing_conditions(self):
        def fixes(path, *, bases_to_try):
            if path == "ignore":
                return None
            assert path in ("source", "empty", "file", "nolines")
            return path

        report_builder = ReportBuilder(
            path_fixer=fixes,
            ignored_lines={},
            sessionid=0,
            current_yaml={
                "codecov": {
                    "max_report_age": None,
                },
                "parsers": {"cobertura": {"handle_missing_conditions": True}},
            },
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = cobertura.from_xml(
            etree.fromstring(xml % ("", int(time()), "", "")), report_builder_session
        )
        processed_report = self.convert_report_to_better_readable(report)
        import pprint

        pprint.pprint(processed_report)
        expected_result = {
            "archive": {
                "file": [
                    (1, 0, "m", [[0, 0, None, None, None]], None, None),
                    (2, 1, "b", [[0, 1, None, None, None]], None, None),
                    (3, 1, None, [[0, 1, None, None, None]], None, None),
                ],
                "source": [
                    (1, 1, None, [[0, 1, None, None, None]], None, None),
                    (2, "0/2", "b", [[0, "0/2", ["exit"], None, None]], None, None),
                    (3, "1/2", "b", [[0, "1/2", ["30"], None, None]], None, None),
                    (4, "2/2", "b", [[0, "2/2", None, None, None]], None, None),
                    (
                        5,
                        "2/4",
                        "b",
                        [[0, "2/4", ["0:jump", "1:jump"], None, None]],
                        None,
                        None,
                    ),
                    (
                        6,
                        "2/4",
                        "b",
                        [[0, "2/4", ["0:jump", "1:jump"], None, None]],
                        None,
                        None,
                    ),
                    (
                        7,
                        "0/2",
                        "b",
                        [[0, "0/2", ["loop", "exit"], None, None]],
                        None,
                        None,
                    ),
                    (8, 1, None, [[0, 1, None, None, None]], None, None),
                    (9, "1/2", "b", [[0, "1/2", ["0"], None, None]], None, None),
                ],
            },
            "report": {
                "files": {
                    "file": [
                        1,
                        [0, 3, 2, 1, 0, "66.66667", 1, 1, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "source": [
                        0,
                        [0, 9, 3, 2, 4, "33.33333", 7, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                },
                "sessions": {},
            },
            "totals": {
                "C": 0,
                "M": 0,
                "N": 0,
                "b": 8,
                "c": "41.66667",
                "d": 1,
                "diff": None,
                "f": 2,
                "h": 5,
                "m": 3,
                "n": 12,
                "p": 4,
                "s": 0,
            },
        }
        assert processed_report["archive"] == expected_result["archive"]
        assert processed_report["report"] == expected_result["report"]
        assert processed_report["totals"] == expected_result["totals"]
        assert processed_report == expected_result

    def test_report_missing_conditions_and_partials_as_hits(self):
        def fixes(path, *, bases_to_try):
            if path == "ignore":
                return None
            assert path in ("source", "empty", "file", "nolines")
            return path

        report_builder = ReportBuilder(
            path_fixer=fixes,
            ignored_lines={},
            sessionid=0,
            current_yaml={
                "codecov": {
                    "max_report_age": None,
                },
                "parsers": {
                    "cobertura": {
                        "handle_missing_conditions": True,
                        "partials_as_hits": True,
                    }
                },
            },
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = cobertura.from_xml(
            etree.fromstring(xml % ("", int(time()), "", "")), report_builder_session
        )
        processed_report = self.convert_report_to_better_readable(report)
        import pprint

        pprint.pprint(processed_report)
        expected_result = {
            "archive": {
                "file": [
                    (1, 0, "m", [[0, 0, None, None, None]], None, None),
                    (2, 1, "b", [[0, 1, None, None, None]], None, None),
                    (3, 1, None, [[0, 1, None, None, None]], None, None),
                ],
                "source": [
                    (1, 1, None, [[0, 1, None, None, None]], None, None),
                    (2, "0/2", "b", [[0, "0/2", ["exit"], None, None]], None, None),
                    (3, 1, None, [[0, 1, None, None, None]], None, None),
                    (4, 1, None, [[0, 1, None, None, None]], None, None),
                    (5, 1, None, [[0, 1, None, None, None]], None, None),
                    (6, 1, None, [[0, 1, None, None, None]], None, None),
                    (
                        7,
                        "0/2",
                        "b",
                        [[0, "0/2", ["loop", "exit"], None, None]],
                        None,
                        None,
                    ),
                    (8, 1, None, [[0, 1, None, None, None]], None, None),
                    (9, 1, None, [[0, 1, None, None, None]], None, None),
                ],
            },
            "report": {
                "files": {
                    "file": [
                        1,
                        [0, 3, 2, 1, 0, "66.66667", 1, 1, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                    "source": [
                        0,
                        [0, 9, 7, 2, 0, "77.77778", 2, 0, 0, 0, 0, 0, 0],
                        None,
                        None,
                    ],
                },
                "sessions": {},
            },
            "totals": {
                "C": 0,
                "M": 0,
                "N": 0,
                "b": 3,
                "c": "75.00000",
                "d": 1,
                "diff": None,
                "f": 2,
                "h": 9,
                "m": 3,
                "n": 12,
                "p": 0,
                "s": 0,
            },
        }
        assert processed_report["archive"] == expected_result["archive"]
        assert processed_report["report"] == expected_result["report"]
        assert processed_report["totals"] == expected_result["totals"]
        assert processed_report == expected_result

    def test_timestamp_zero_passes(self):
        # Some reports have timestamp as a string zero, check we can handle that
        timestring = "0"
        report_builder = ReportBuilder(
            path_fixer=lambda path, bases_to_try: path,
            ignored_lines={},
            sessionid=0,
            current_yaml={"codecov": {"max_report_age": "12h"}},
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = cobertura.from_xml(
            etree.fromstring(xml % ("", timestring, "", "")), report_builder_session
        )
        processed_report = self.convert_report_to_better_readable(report)
        assert len(processed_report["archive"]["file"]) == 3
        assert processed_report["totals"]["c"] == "41.66667"

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
        with pytest.raises(ReportExpiredException, match="Cobertura report expired"):
            report_builder = ReportBuilder(
                path_fixer=None,
                ignored_lines={},
                sessionid=0,
                current_yaml=None,
            )
            report_builder_session = report_builder.create_report_builder_session(
                "filename"
            )
            cobertura.from_xml(
                etree.fromstring(xml % ("", date, "", "")), report_builder_session
            )

        with pytest.raises(ReportExpiredException, match="Cobertura report expired"):
            report_builder = ReportBuilder(
                path_fixer=None,
                ignored_lines={},
                sessionid=0,
                current_yaml=None,
            )
            report_builder_session = report_builder.create_report_builder_session(
                "filename"
            )
            cobertura.from_xml(
                etree.fromstring(xml % ("s", date, "", "s")), report_builder_session
            )

    def test_matches_content(self):
        processor = cobertura.CoberturaProcessor()
        content = etree.fromstring(xml % ("", int(time()), "", ""))
        first_line = xml.split("\n", 1)[0]
        name = "coverage.xml"
        assert processor.matches_content(content, first_line, name)

    def test_not_matches_content(self):
        processor = cobertura.CoberturaProcessor()
        content = etree.fromstring(
            """<?xml version="1.0" standalone="yes"?>
            <CoverageDSPriv>
              <Lines>
                <LnStart>258</LnStart>
                <ColStart>0</ColStart>
                <LnEnd>258</LnEnd>
                <ColEnd>0</ColEnd>
                <Coverage>1</Coverage>
                <SourceFileID>1</SourceFileID>
                <LineID>0</LineID>
              </Lines>
            </CoverageDSPriv>"""
        )
        first_line = xml.split("\n", 1)[0]
        name = "coverage.xml"
        assert not processor.matches_content(content, first_line, name)

    def test_use_source_for_filename_if_one_path_source(self):
        sources = """
        <sources>
            <source>/user/repo</source>
        </sources>
        """
        processor = cobertura.CoberturaProcessor()
        report_builder = ReportBuilder(
            path_fixer=lambda path, bases_to_try: [
                os.path.join(b, path) for b in bases_to_try
            ][0],
            ignored_lines={},
            sessionid=0,
            current_yaml={"codecov": {"max_report_age": None}},
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = cobertura.from_xml(
            etree.fromstring(xml % ("", int(time()), sources, "")),
            report_builder_session,
        )
        processed_report = self.convert_report_to_better_readable(report)
        # prepend the source
        assert "/user/repo/source" in processed_report["report"]["files"]
        assert "/user/repo/file" in processed_report["report"]["files"]

    def test_use_source_for_filename_if_one_bad_source(self):
        sources = """
        <sources>
            <source>not a path</source>
        </sources>
        """
        processor = cobertura.CoberturaProcessor()
        report_builder = ReportBuilder(
            path_fixer=lambda path, bases_to_try: path,
            ignored_lines={},
            sessionid=0,
            current_yaml={"codecov": {"max_report_age": None}},
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = cobertura.from_xml(
            etree.fromstring(xml % ("", int(time()), sources, "")),
            report_builder_session,
        )
        processed_report = self.convert_report_to_better_readable(report)
        # doesnt use the source
        assert "source" in processed_report["report"]["files"]
        assert "file" in processed_report["report"]["files"]

    def test_use_source_for_filename_if_multiple_sources_only_second_works(self):
        sources = """
        <sources>
            <source>/here</source>
            <source>/there</source>
        </sources>
        """
        path_fixer = PathFixer([], [], ["/there/source", "/there/file"])
        report_builder = ReportBuilder(
            path_fixer=path_fixer.get_relative_path_aware_pathfixer("/somewhere"),
            ignored_lines={},
            sessionid=0,
            current_yaml={"codecov": {"max_report_age": None}},
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = cobertura.from_xml(
            etree.fromstring(xml % ("", int(time()), sources, "")),
            report_builder_session,
        )
        processed_report = self.convert_report_to_better_readable(report)
        # doesnt use the source as we dont know which one
        assert "/there/source" in processed_report["report"]["files"]
        assert "/there/file" in processed_report["report"]["files"]

    def test_use_source_for_filename_if_multiple_sources_works_without_base(self):
        sources = """
        <sources>
            <source>/here</source>
            <source>/there</source>
        </sources>
        """
        path_fixer = PathFixer([], [], ["source", "file", "/here/source"])
        report_builder = ReportBuilder(
            path_fixer=path_fixer.get_relative_path_aware_pathfixer("/somewhere"),
            ignored_lines={},
            sessionid=0,
            current_yaml={"codecov": {"max_report_age": None}},
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = cobertura.from_xml(
            etree.fromstring(xml % ("", int(time()), sources, "")),
            report_builder_session,
        )
        processed_report = self.convert_report_to_better_readable(report)
        # doesnt use the source as we dont know which one
        assert "source" in processed_report["report"]["files"]
        assert "file" in processed_report["report"]["files"]

    def test_use_source_for_filename_if_multiple_sources_first_and_second_works(self):
        sources = """
        <sources>
            <source>/here</source>
            <source>/there</source>
        </sources>
        """
        path_fixer = PathFixer(
            [], [], ["/here/source", "/there/source", "/here/file", "/there/file"]
        )
        report_builder = ReportBuilder(
            path_fixer=path_fixer.get_relative_path_aware_pathfixer("/somewhere"),
            ignored_lines={},
            sessionid=0,
            current_yaml={"codecov": {"max_report_age": None}},
        )
        report_builder_session = report_builder.create_report_builder_session(
            "filename"
        )
        report = cobertura.from_xml(
            etree.fromstring(xml % ("", int(time()), sources, "")),
            report_builder_session,
        )
        processed_report = self.convert_report_to_better_readable(report)
        # doesnt use the source as we dont know which one
        assert "/here/source" in processed_report["report"]["files"]
        assert "/here/file" in processed_report["report"]["files"]
