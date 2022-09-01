import xml.etree.cElementTree as etree
from time import time

import pytest

from helpers.exceptions import ReportExpiredException
from services.report.languages import jacoco
from services.report.report_builder import ReportBuilder
from tests.base import BaseTestCase

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
    def test_report(self):
        def fixes(path):
            if path == "base/ignore":
                return None
            assert path in ("base/source.java", "base/file.java", "base/empty")
            return path

        report_builder = ReportBuilder(
            current_yaml={}, sessionid=0, ignored_lines={}, path_fixer=fixes
        )
        report_builder_session = report_builder.create_report_builder_session(
            "file_name"
        )
        report = jacoco.from_xml(
            etree.fromstring(xml % int(time())), report_builder_session
        )
        processed_report = self.convert_report_to_better_readable(report)
        import pprint

        pprint.pprint(processed_report["archive"])
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
        )

        def fixes(path):
            if module == "a":
                return path if "src/main/java" not in path else None
            else:
                return path if "src/main/java" in path else None

        report_builder = ReportBuilder(
            current_yaml={}, sessionid=0, ignored_lines={}, path_fixer=fixes
        )
        report_builder_session = report_builder.create_report_builder_session(
            "file_name"
        )
        report = jacoco.from_xml(etree.fromstring(data), report_builder_session)
        processed_report = self.convert_report_to_better_readable(report)
        assert [path] == list(processed_report["archive"].keys())

    @pytest.mark.parametrize("date", [(int(time()) - 172800), "01-01-2014"])
    def test_expired(self, date):
        report_builder = ReportBuilder(
            current_yaml={}, sessionid=0, ignored_lines={}, path_fixer=None
        )
        report_builder_session = report_builder.create_report_builder_session(
            "file_name"
        )
        with pytest.raises(ReportExpiredException, match="Jacoco report expired"):
            jacoco.from_xml(etree.fromstring(xml % date), report_builder_session)
