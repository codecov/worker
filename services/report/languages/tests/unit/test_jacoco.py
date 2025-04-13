import datetime
import logging
from time import time

import pytest
from lxml import etree
from pytest import LogCaptureFixture

from helpers.exceptions import ReportExpiredException
from services.report.languages import jacoco
from test_utils.base import BaseTestCase

from . import create_report_builder_session

xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<!DOCTYPE report PUBLIC "-//JACOCO//DTD Report 1.0//EN" "report.dtd">
<report name="JaCoCo Maven plug-in example for Java project">
    <sessioninfo id="Steves-MBP.local-b048b758" start="%s" dump="1411925088117" />
    <package name="base">
        <class name="base/source">
          <method name="&lt;init&gt;" line="1">
            <counter type="INSTRUCTION" missed="54" covered="0" />
            <counter type="BRANCH" missed="4" covered="0" />
            <counter type="LINE" missed="2" covered="0" />
            <counter type="COMPLEXITY" missed="3" covered="1" />
            <counter type="METHOD" missed="1" covered="0" />
          </method>
          <method name="ignore"></method>
          <method name="ignore$" line="2">
            <counter type="INSTRUCTION" missed="60" covered="22" />
            <counter type="BRANCH" missed="3" covered="3" />
            <counter type="LINE" missed="0" covered="5" />
            <counter type="COMPLEXITY" missed="3" covered="1" />
            <counter type="METHOD" missed="0" covered="1" />
          </method>
        </class>
        <sourcefile name="source.java">
            <line nr="0" mi="0" ci="20" mb="0" cb="0" />
            <line nr="1" mi="99" ci="99" mb="0" cb="2" />
            <line nr="2" mi="0" ci="2" mb="1" cb="1" />
            <line nr="3" mi="1" ci="0" mb="0" cb="0" />
            <line nr="4" mi="0" ci="2" mb="0" cb="0" />
        </sourcefile>
        <sourcefile name="file.java">
            <line nr="1" mi="0" ci="1" mb="0" cb="0" />
        </sourcefile>
        <sourcefile name="ignore">
            <line nr="1" mi="0" ci="1" mb="0" cb="0" />
        </sourcefile>
        <sourcefile name="empty">
        </sourcefile>
    </package>
</report>
"""


class TestJacoco(BaseTestCase):
    @pytest.fixture(autouse=True)
    def inject_fixtures(self, caplog: LogCaptureFixture):
        self.caplog = caplog

    def test_report(self):
        def fixes(path):
            if path == "base/ignore":
                return None
            assert path in ("base/source.java", "base/file.java", "base/empty")
            return path

        report_builder_session = create_report_builder_session(path_fixer=fixes)

        with self.caplog.at_level(logging.WARNING, logger=jacoco.__name__):
            jacoco.from_xml(
                etree.fromstring((xml % int(time())).encode()), report_builder_session
            )

            assert (
                self.caplog.records[-1].message
                == "Jacoco report has an invalid coverage line: nr=0. Skipping processing line."
            )

        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        expected_result_archive = {
            "base/file.java": [(1, 1, None, [[0, 1, None, None, None]], None, None)],
            "base/source.java": [
                (1, "2/2", "m", [[0, "2/2", None, None, (1, 4)]], None, (1, 4)),
                (2, "1/2", "m", [[0, "1/2", None, None, (1, 4)]], None, (1, 4)),
                (3, 0, None, [[0, 0, None, None, None]], None, None),
                (4, 2, None, [[0, 2, None, None, None]], None, None),
            ],
        }

        assert expected_result_archive == processed_report["archive"]

    def test_report_partials_as_hits(self):
        def fixes(path):
            if path == "base/ignore":
                return None
            assert path in ("base/source.java", "base/file.java", "base/empty")
            return path

        report_builder_session = create_report_builder_session(
            current_yaml={"parsers": {"jacoco": {"partials_as_hits": True}}},
            path_fixer=fixes,
        )
        jacoco.from_xml(
            etree.fromstring((xml % int(time())).encode()), report_builder_session
        )
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        expected_result_archive = {
            "base/file.java": [(1, 1, None, [[0, 1, None, None, None]], None, None)],
            "base/source.java": [
                (1, "2/2", "m", [[0, "2/2", None, None, (1, 4)]], None, (1, 4)),
                (2, 1, "m", [[0, 1, None, None, (1, 4)]], None, (1, 4)),
                (3, 0, None, [[0, 0, None, None, None]], None, None),
                (4, 2, None, [[0, 2, None, None, None]], None, None),
            ],
        }

        assert expected_result_archive == processed_report["archive"]

    @pytest.mark.parametrize(
        "module, path",
        [("a", "module_a/package/file"), ("b", "module_b/src/main/java/package/file")],
    )
    def test_multi_module(self, module, path):
        data = (
            """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
        <!DOCTYPE report PUBLIC "-//JACOCO//DTD Report 1.0//EN" "report.dtd">
        <report name="module_%s">
            <package name="package">
                <sourcefile name="file">
                    <line nr="1" mi="0" ci="2" mb="0" cb="0" />
                </sourcefile>
            </package>
        </report>"""
            % module
        ).encode()

        def fixes(path):
            if module == "a":
                return path if "src/main/java" not in path else None
            else:
                return path if "src/main/java" in path else None

        report_builder_session = create_report_builder_session(path_fixer=fixes)
        jacoco.from_xml(etree.fromstring(data), report_builder_session)
        report = report_builder_session.output_report()
        processed_report = self.convert_report_to_better_readable(report)

        assert [path] == list(processed_report["archive"].keys())

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
        report_builder_session = create_report_builder_session()

        with pytest.raises(ReportExpiredException, match="Jacoco report expired"):
            jacoco.from_xml(
                etree.fromstring((xml % date).encode()), report_builder_session
            )
