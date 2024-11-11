from json import loads
from pathlib import Path
from unittest.mock import patch

import pytest
from lxml import etree
from shared.reports.resources import LineSession, Report, ReportFile, ReportLine
from shared.reports.types import ReportTotals
from shared.utils.sessions import Session
from shared.yaml import UserYaml

from helpers.exceptions import (
    CorruptRawReportError,
    ReportEmptyError,
    ReportExpiredException,
)
from services.report import raw_upload_processor as process
from services.report.parser import LegacyReportParser
from services.report.parser.types import LegacyParsedRawReport, ParsedUploadedReportFile
from services.report.report_builder import ReportBuilder
from test_utils.base import BaseTestCase

here = Path(__file__)
folder = here.parent


@pytest.mark.skip(reason="this is supposed to be invoked manually")
def test_manual():
    # The intention of this test is to easily reproduce production problems with real reports.
    # So download the relevant report, fill in its filename below, comment out the `skip` annotation,
    # and run this test directly.
    filename = "..."
    with open(filename, "rb") as d:
        contents = d.read()

    parsed_report = LegacyReportParser().parse_raw_report_from_bytes(contents)
    master = process.process_raw_upload(None, parsed_report, Session())

    assert not master.is_empty()


class TestProcessRawUpload(BaseTestCase):
    def readjson(self, filename):
        with open(folder / filename, "r") as d:
            contents = loads(d.read())
            return contents

    def get_v3_report(self):
        filename = "report.v3.json"
        with open(folder / filename, "r") as d:
            contents = loads(d.read())
            return Report(**contents)

    @property
    def data(self):
        return {"yaml": {}}

    @pytest.mark.parametrize("keys", ["nm", "n", "m", "nme", "ne", "M"])
    def test_process_raw_upload(self, keys):
        report = []
        # add env
        if "e" in keys:
            report.append("A=b")
            report.append("<<<<<< ENV")

        # add network
        if "n" in keys:
            report.append("path/to/file")
            report.append("<<<<<< network")

        # add report
        report.append("# path=app.coverage.txt")
        report.append("/file:\n 1 | 1|line")

        if "m" in keys:
            report.append("<<<<<< EOF")
            report.append("# path=app.coverage.txt")
            report.append("/file2:\n 1 | 1|line")

        parsed_report = LegacyReportParser().parse_raw_report_from_bytes(
            "\n".join(report).encode()
        )
        master = process.process_raw_upload(None, parsed_report, Session())

        if "e" in keys:
            assert master.sessions[0].env == {"A": "b"}

        assert master.totals.files == 1 + (
            1 if ("m" in keys and "n" not in keys) else 0
        )
        assert master.totals.sessions == 1

        if "n" in keys:
            assert master.get("path/to/file")
            assert master["path/to/file"][1].coverage == 1
        else:
            assert master.get("file")
            assert master["file"][1].coverage == 1
        assert ("file2" in master) is ("m" in keys and "n" not in keys)

    def test_process_raw_upload_skipped_files(self):
        lcov_section = [
            "TN:",
            "SF:file.js",
            "FNDA:76,jsx",
            "FN:76,(anonymous_1)",
            "removed",
            "DA:0,skipped",
            "DA:null,skipped",
            "DA:1,1",
            "DA:=,=",
            "BRDA:0,1,0,1",
            "BRDA:0,1,0,1",
            "BRDA:1,1,0,1",
            "BRDA:1,1,1,1",
            "end_of_record",
        ]
        json_section = [
            "{",
            '    "coverage": {',
            '        "source": [null, 1],',
            '        "file": {"1": 1, "2": "1", "3": true, "4": "1/2"},',
            '        "empty": {}',
            "    },",
            '    "messages": {',
            '        "source": {',
            '            "1": "Message"',
            "        }",
            "    }",
            "}",
        ]
        report = []
        report.append("# path=coverage/coverage.lcov")
        report.extend(lcov_section)
        report.append("<<<<<< EOF")
        report.append("# path=coverage/coverage.json")
        report.extend(json_section)

        parsed_report = LegacyReportParser().parse_raw_report_from_bytes(
            "\n".join(report).encode()
        )
        master = process.process_raw_upload({}, parsed_report, Session())
        assert master.files == ["source", "file"]

    def test_process_raw_upload_empty_report(self):
        report_data = []
        report_data.append("# path=coverage/coverage.txt")
        report_data.extend(["5"])
        report_data.append("<<<<<< EOF")
        report_data.append("# path=coverage/other.txt")
        report_data.append("json_section")

        original_report = Report()
        first_file = ReportFile("file_1.go")
        first_file.append(
            1, ReportLine.create(coverage=1, sessions=[[0, 1]], complexity=(10, 2))
        )
        first_file.append(2, ReportLine.create(coverage=0, sessions=[[0, 1]]))
        first_file.append(3, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        first_file.append(5, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        first_file.append(6, ReportLine.create(coverage=0, sessions=[[0, 1]]))
        first_file.append(8, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        first_file.append(9, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        first_file.append(10, ReportLine.create(coverage=0, sessions=[[0, 1]]))
        second_file = ReportFile("file_2.py")
        second_file.append(12, ReportLine.create(coverage=1, sessions=[[0, 1]]))
        second_file.append(
            51, ReportLine.create(coverage="1/2", type="b", sessions=[[0, 1]])
        )
        original_report.append(first_file)
        original_report.append(second_file)
        original_report.add_session(Session(flags=["unit"]))
        assert len(original_report.sessions) == 1

        parsed_report = LegacyReportParser().parse_raw_report_from_bytes(
            "\n".join(report_data).encode()
        )
        with pytest.raises(ReportEmptyError):
            process.process_raw_upload(
                UserYaml({}), parsed_report, Session(flags=["fruits"])
            )
        assert len(original_report.sessions) == 1
        assert sorted(original_report.flags.keys()) == ["unit"]
        assert original_report.files == ["file_1.go", "file_2.py"]
        assert original_report.flags["unit"].totals == ReportTotals(
            files=2,
            lines=10,
            hits=10,
            misses=0,
            partials=0,
            coverage="100",
            branches=1,
            methods=0,
            messages=0,
            sessions=1,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        assert original_report.flags.get("fruits") is None
        general_totals, json_data = original_report.to_database()
        assert general_totals == {
            "f": 2,
            "n": 10,
            "h": 6,
            "m": 3,
            "p": 1,
            "c": "60.00000",
            "b": 1,
            "d": 0,
            "M": 0,
            "s": 1,
            "C": 10,
            "N": 2,
            "diff": None,
        }
        assert loads(json_data) == {
            "files": {
                "file_1.go": [
                    0,
                    [0, 8, 5, 3, 0, "62.50000", 0, 0, 0, 0, 10, 2, 0],
                    None,
                    None,
                ],
                "file_2.py": [
                    1,
                    [0, 2, 1, 0, 1, "50.00000", 1, 0, 0, 0, 0, 0, 0],
                    None,
                    None,
                ],
            },
            "sessions": {
                "0": {
                    "t": None,
                    "d": None,
                    "a": None,
                    "f": ["unit"],
                    "c": None,
                    "n": None,
                    "N": None,
                    "j": None,
                    "u": None,
                    "p": None,
                    "e": None,
                    "st": "uploaded",
                    "se": {},
                }
            },
        }

    def test_none(self):
        with pytest.raises(ReportEmptyError, match="No files found in report."):
            parsed_report = LegacyReportParser().parse_raw_report_from_bytes(b"")
            process.process_raw_upload(None, parsed_report, Session())


class TestProcessRawUploadFixed(BaseTestCase):
    def test_fixes(self):
        report_lines = [
            "# path=coverage.info",
            "mode: count",
            "file.go:7.14,9.2 1 1",
            "<<<<<< EOF",
            "# path=fixes",
            "file.go:8:",
            "<<<<<< EOF",
            "",
        ]
        parsed_report = LegacyReportParser().parse_raw_report_from_bytes(
            "\n".join(report_lines).encode()
        )
        report = process.process_raw_upload({}, parsed_report, Session())

        assert 2 not in report["file.go"], "2 never existed"
        assert report["file.go"][7].coverage == 1
        assert 8 not in report["file.go"], "8 should have been removed"
        assert 9 not in report["file.go"], "9 should have been removed"


class TestProcessRawUploadFlags(BaseTestCase):
    @pytest.mark.parametrize(
        "flag",
        [{"paths": ["!tests/.*"]}, {"ignore": ["tests/.*"]}, {"paths": ["folder/"]}],
    )
    def test_flags(self, flag):
        parsed_report = LegacyReportParser().parse_raw_report_from_bytes(
            b'{"coverage": {"tests/test.py": [null, 0], "folder/file.py": [null, 1]}}'
        )
        master = process.process_raw_upload(
            UserYaml({"flags": {"docker": flag}}),
            parsed_report,
            Session(flags=["docker"]),
        )

        assert master.files == ["folder/file.py"]
        assert master.sessions[0].flags == ["docker"]


class TestProcessReport(BaseTestCase):
    @pytest.mark.parametrize("report", [b"<idk>", b"<?xml", b""])
    def test_emptys(self, report):
        res = process.process_report(
            report=ParsedUploadedReportFile(filename=None, file_contents=report),
            report_builder=ReportBuilder(
                current_yaml=None, sessionid=0, ignored_lines={}, path_fixer=str
            ),
        )

        assert res is None

    def test_fixes_paths(self):
        res = process.process_report(
            report=ParsedUploadedReportFile(
                filename="app.coverage.txt",
                file_contents=b"/file:\n 1 | 1|line",
            ),
            report_builder=ReportBuilder(
                current_yaml=None, sessionid=0, ignored_lines={}, path_fixer=str
            ),
        )

        assert res.get("file") is not None

    def test_report_fixes_same_final_result(self):
        commit_yaml = {"fixes": ["arroba::prefix", "bingo::prefix"]}
        parsed_report = LegacyReportParser().parse_raw_report_from_bytes(
            b'{"coverage": {"arroba/test.py": [null, 0], "bingo/test.py": [null, 1]}}'
        )
        master = process.process_raw_upload(
            UserYaml(commit_yaml), parsed_report, Session()
        )

        assert len(master.files) == 1
        assert master.files[0] == "prefix/test.py"

    @pytest.mark.parametrize(
        "lang, report",
        [
            (
                "go.from_txt",
                ParsedUploadedReportFile(filename=None, file_contents=b"mode: atomic"),
            ),
            (
                "xcode.from_txt",
                ParsedUploadedReportFile(
                    filename="/Users/path/to/app.coverage.txt", file_contents=b"<data>"
                ),
            ),
            (
                "xcode.from_txt",
                ParsedUploadedReportFile(
                    filename="app.coverage.txt", file_contents=b"<data>"
                ),
            ),
            (
                "xcode.from_txt",
                ParsedUploadedReportFile(
                    filename="/Users/path/to/framework.coverage.txt",
                    file_contents=b"<data>",
                ),
            ),
            (
                "xcode.from_txt",
                ParsedUploadedReportFile(
                    filename="framework.coverage.txt", file_contents=b"<data>"
                ),
            ),
            (
                "xcode.from_txt",
                ParsedUploadedReportFile(
                    filename="/Users/path/to/xctest.coverage.txt",
                    file_contents=b"<data>",
                ),
            ),
            (
                "xcode.from_txt",
                ParsedUploadedReportFile(
                    filename="xctest.coverage.txt", file_contents=b"<data>"
                ),
            ),
            (
                "xcode.from_txt",
                ParsedUploadedReportFile(
                    filename="coverage.txt", file_contents=b"/blah/app.h:\n"
                ),
            ),
            (
                "dlst.from_string",
                ParsedUploadedReportFile(filename=None, file_contents=b"data\ncovered"),
            ),
            (
                "vb.from_xml",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b"<results><SampleTag></SampleTag></results>",
                ),
            ),
            (
                "lcov.from_txt",
                ParsedUploadedReportFile(
                    filename=None, file_contents=b"content\nend_of_record"
                ),
            ),
            (
                "gcov.from_txt",
                ParsedUploadedReportFile(
                    filename=None, file_contents=b"0:Source:\nline2"
                ),
            ),
            (
                "lua.from_txt",
                ParsedUploadedReportFile(filename=None, file_contents=b"======="),
            ),
            (
                "gap.from_string",
                ParsedUploadedReportFile(
                    filename=None, file_contents=b'{"Type": "S", "File": "a"}'
                ),
            ),
            (
                "gap.from_string",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b'{"Type": "S", "File": "a"}\n{"Type":"R","Line":1,"FileId":37}',
                ),
            ),
            (
                "v1.from_json",
                ParsedUploadedReportFile(
                    filename=None, file_contents=b'{"RSpec": {"coverage": {}}}'
                ),
            ),
            (
                "v1.from_json",
                ParsedUploadedReportFile(
                    filename=None, file_contents=b'{"MiniTest": {"coverage": {}}}'
                ),
            ),
            (
                "v1.from_json",
                ParsedUploadedReportFile(
                    filename=None, file_contents=b'{"coverage": {}}'
                ),
            ),
            (
                "v1.from_json",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=('{"coverage": {"data": "' + "\xf1" + '"}}').encode(),
                ),
            ),
            (
                "rlang.from_json",
                ParsedUploadedReportFile(
                    filename=None, file_contents=b'{"uploader": "R"}'
                ),
            ),
            (
                "scala.from_json",
                ParsedUploadedReportFile(
                    filename=None, file_contents=b'{"fileReports": ""}'
                ),
            ),
            (
                "coveralls.from_json",
                ParsedUploadedReportFile(
                    filename=None, file_contents=b'{"source_files": ""}'
                ),
            ),
            (
                "node.from_json",
                ParsedUploadedReportFile(
                    filename=None, file_contents=b'{"filename": {"branchMap": ""}}'
                ),
            ),
            (
                "scoverage.from_xml",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=(
                        "<statements><data>" + "\xf1" + "</data></statements>"
                    ).encode(),
                ),
            ),
            (
                "clover.from_xml",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b'<coverage generated="abc"><SampleTag></SampleTag></coverage>',
                ),
            ),
            (
                "cobertura.from_xml",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b"<coverage><SampleTag></SampleTag></coverage>",
                ),
            ),
            (
                "csharp.from_xml",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b"<CoverageSession><SampleTag></SampleTag></CoverageSession>",
                ),
            ),
            (
                "jacoco.from_xml",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b"<report><SampleTag></SampleTag></report>",
                ),
            ),
            (
                "xcodeplist.from_xml",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b'<?xml version="1.0">\n<plist version="1.0">',
                ),
            ),
            (
                "xcodeplist.from_xml",
                ParsedUploadedReportFile(
                    filename="3CB41F9A-1DEA-4DE1-B321-6F462C460DB6.xccoverage.plist",
                    file_contents=b"__",
                ),
            ),
            (
                "scoverage.from_xml",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b'<?xml version="1.0" encoding="utf-8"?>\n<statements><SampleTag></SampleTag></statements>',
                ),
            ),
            (
                "clover.from_xml",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b'<?xml version="1.0" encoding="utf-8"?>\n<coverage generated="abc"><SampleTag></SampleTag></coverage>',
                ),
            ),
            (
                "cobertura.from_xml",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b'<?xml version="1.0" encoding="utf-8"?>\n<coverage><SampleTag></SampleTag></coverage>',
                ),
            ),
            (
                "csharp.from_xml",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b'<?xml version="1.0" encoding="utf-8"?>\n<CoverageSession><SampleTag></SampleTag></CoverageSession>',
                ),
            ),
            (
                "jacoco.from_xml",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b'<?xml version="1.0" encoding="utf-8"?>\n<report><SampleTag></SampleTag></report>',
                ),
            ),
            (
                "salesforce.from_json",
                ParsedUploadedReportFile(
                    filename=None, file_contents=b'[{"name": "banana"}]'
                ),
            ),
            (
                "bullseye.from_xml",
                ParsedUploadedReportFile(
                    filename=None,
                    file_contents=b'<?xml version="1.0" encoding="UTF-8"?><BullseyeCoverage name="test.cov" dir="c:/project/cov/sample/" buildId="1234_%s" version="6" xmlns="https://www.bullseye.com/covxml" fn_cov="29" fn_total="29" cd_cov="108" cd_total="161" d_cov="107" d_total="153"><folder name="calc" fn_cov="10" fn_total="10" cd_cov="21" cd_total="50" d_cov="21" d_total="50"></folder></BullseyeCoverage>',
                ),
            ),
        ],
    )
    def test_detect(self, lang, report):
        with patch("services.report.languages.%s" % lang) as func:
            res = process.process_report(
                report=report,
                report_builder=ReportBuilder(
                    current_yaml=None, sessionid=0, ignored_lines={}, path_fixer=str
                ),
            )

            assert res is not None
            assert func.called

    @pytest.mark.parametrize(
        "report",
        [(ParsedUploadedReportFile(filename=None, file_contents=b'[{"a": "banana"}]'))],
    )
    def test_detect_nothing_found(self, report):
        res = process.process_report(
            report=report,
            report_builder=ReportBuilder(
                current_yaml=None, sessionid=0, ignored_lines={}, path_fixer=str
            ),
        )
        assert res is None

    def test_xxe_entity_not_called(self, mocker):
        report_xxe_xml = b"""<?xml version="1.0"?>
        <!DOCTYPE coverage [
        <!ELEMENT coverage ANY >
        <!ENTITY xxe SYSTEM "file:///config/codecov.yml" >]>
        <statements><statement>&xxe;</statement></statements>
        """
        func = mocker.patch("services.report.languages.scoverage.from_xml")
        process.process_report(
            report=ParsedUploadedReportFile(
                filename="filename", file_contents=report_xxe_xml
            ),
            report_builder=ReportBuilder(
                current_yaml=None, sessionid=0, ignored_lines={}, path_fixer=str
            ),
        )
        assert func.called
        # should be from_xml(xml, report_builder_session). Don't have direct ref to builder_session, so using Mocker.ANY
        func.assert_called_with(mocker.ANY, mocker.ANY)
        expected_xml_string = "<statements><statement>&xxe;</statement></statements>"
        output_xml_string = etree.tostring(func.call_args_list[0][0][0]).decode()
        assert output_xml_string == expected_xml_string

    def test_format_not_recognized(self, mocker):
        mocked = mocker.patch("services.report.report_processor.report_type_matching")
        mocked.return_value = "bad_processing", "new_type"
        r = ParsedUploadedReportFile(
            filename="/Users/path/to/app.coverage.txt",
            file_contents=b"<data>",
        )
        result = process.process_report(
            report=r,
            report_builder=ReportBuilder(
                current_yaml=None, sessionid=0, ignored_lines={}, path_fixer=str
            ),
        )
        assert result is None
        assert mocked.called
        mocked.assert_called_with(r, "<data>")

    def test_process_report_exception_raised(self, mocker):
        class SpecialUnexpectedException(Exception):
            pass

        mocker.patch(
            "services.report.report_processor.report_type_matching",
            return_value=(b"", "plist"),
        )
        mocker.patch(
            "services.report.report_processor.XCodePlistProcessor.matches_content",
            return_value=True,
        )
        mocker.patch(
            "services.report.report_processor.XCodePlistProcessor.process",
            side_effect=SpecialUnexpectedException(),
        )

        with pytest.raises(SpecialUnexpectedException):
            process.process_report(
                report=ParsedUploadedReportFile(
                    filename="/Users/path/to/app.coverage.txt",
                    file_contents=b"<data>",
                ),
                report_builder=ReportBuilder(
                    current_yaml=None, sessionid=0, ignored_lines={}, path_fixer=str
                ),
            )

    def test_process_report_corrupt_format(self, mocker):
        mocker.patch(
            "services.report.report_processor.report_type_matching",
            return_value=(b"", "plist"),
        )
        mocker.patch(
            "services.report.report_processor.XCodePlistProcessor.matches_content",
            return_value=True,
        )
        mocker.patch(
            "services.report.report_processor.XCodePlistProcessor.process",
            side_effect=CorruptRawReportError("expected_format", "error_explanation"),
        )

        res = process.process_report(
            report=ParsedUploadedReportFile(
                filename="/Users/path/to/app.coverage.txt",
                file_contents=b"<data>",
            ),
            report_builder=ReportBuilder(
                current_yaml=None, sessionid=0, ignored_lines={}, path_fixer=str
            ),
        )
        assert res is None

    def test_process_raw_upload_multiple_raw_reports(self, mocker):
        first_raw_report_result = Report()
        first_banana = ReportFile("banana.py")
        first_banana.append(1, ReportLine.create(1, sessions=[LineSession(0, 1)]))
        first_banana.append(2, ReportLine.create(0, sessions=[LineSession(0, 0)]))
        first_raw_report_result.append(first_banana)
        second_raw_report_result = Report()
        second_banana = ReportFile("banana.py")
        second_banana.append(2, ReportLine.create(1, sessions=[LineSession(0, 1)]))
        second_banana.append(3, ReportLine.create(0, sessions=[LineSession(0, 0)]))
        second_raw_report_result.append(second_banana)
        second_another_file = ReportFile("another.c")
        second_another_file.append(
            2, ReportLine.create(0, sessions=[LineSession(0, 0)])
        )
        second_another_file.append(
            3, ReportLine.create(1, sessions=[LineSession(0, 1)])
        )
        second_raw_report_result.append(second_another_file)
        third_raw_report_result = Report()
        third_banana = ReportFile("banana.py")
        third_banana.append(
            3, ReportLine.create("1/2", sessions=[LineSession(0, "1/2")])
        )
        third_banana.append(5, ReportLine.create(0, sessions=[LineSession(0, 0)]))
        third_raw_report_result.append(third_banana)
        uploaded_reports = LegacyParsedRawReport(
            toc=None,
            env=None,
            report_fixes=None,
            uploaded_files=[
                ParsedUploadedReportFile(
                    filename="/Users/path/to/app.coverage.txt",
                    file_contents=b"<data>",
                ),
                ParsedUploadedReportFile(
                    filename="/Users/path/to/app.coverage.txt",
                    file_contents=b"<data>",
                ),
                ParsedUploadedReportFile(
                    filename="/Users/path/to/app.coverage.txt",
                    file_contents=b"<data>",
                ),
            ],
        )
        mocker.patch.object(
            process,
            "process_report",
            side_effect=[
                first_raw_report_result,
                second_raw_report_result,
                third_raw_report_result,
            ],
        )
        session = Session(flags=["flag_one", "flag_two"])
        res = process.process_raw_upload(UserYaml({}), uploaded_reports, session)

        assert session.totals == ReportTotals(
            files=2,
            lines=6,
            hits=3,
            misses=2,
            partials=1,
            coverage="50.00000",
            branches=0,
            methods=0,
            messages=0,
            sessions=1,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        assert sorted(res.files) == ["another.c", "banana.py"]
        assert res.get("banana.py").totals == ReportTotals(
            files=0,
            lines=4,
            hits=2,
            misses=1,
            partials=1,
            coverage="50.00000",
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        assert res.get("another.c").totals == ReportTotals(
            files=0,
            lines=2,
            hits=1,
            misses=1,
            partials=0,
            coverage="50.00000",
            branches=0,
            methods=0,
            messages=0,
            sessions=0,
            complexity=0,
            complexity_total=0,
            diff=0,
        )
        assert sorted(res.sessions.keys()) == [0]
        assert res.sessions[0] == session

    def test_process_raw_upload_expired_report(self, mocker):
        filename = "/Users/path/to/app.coverage.txt"
        uploaded_reports = LegacyParsedRawReport(
            toc=None,
            env=None,
            report_fixes=None,
            uploaded_files=[
                ParsedUploadedReportFile(
                    filename="/Users/path/to/app.coverage.txt",
                    file_contents=b"<data>",
                ),
            ],
        )
        mocker.patch.object(
            process,
            "process_report",
            side_effect=[
                ReportExpiredException(),
            ],
        )
        session = Session(flags=["flag_one", "flag_two"])
        with pytest.raises(ReportExpiredException) as e:
            _ = process.process_raw_upload(UserYaml({}), uploaded_reports, session)

        assert e.value.filename == filename
