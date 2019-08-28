from unittest.mock import patch, Mock
from lxml import etree
import pytest
from json import loads
from pathlib import Path
from tests.base import BaseTestCase
from services.report import raw_upload_processor as process
from covreports.utils.tuples import ReportTotals
from covreports.utils.sessions import Session
from covreports.resources import Report

here = Path(__file__)
folder = here.parent


class TestProcessRawUpload(BaseTestCase):

    def readjson(self, filename):
        with open(folder / filename, 'r') as d:
            contents = loads(d.read())
            return contents

    def get_v3_report(self):
        filename = 'report.v3.json'
        with open(folder / filename, 'r') as d:
            contents = loads(d.read())
            return Report(**contents)

    @property
    def data(self):
        return {'yaml': {}}

    @pytest.mark.parametrize("keys", ['nm', 'n', 'm', 'nme', 'ne', 'M'])
    def test_process_raw_upload(self, keys):
        report = []
        # add env
        if 'e' in keys:
            report.append('A=b')
            report.append('<<<<<< ENV')

        # add network
        if 'n' in keys:
            report.append('path/to/file')
            report.append('<<<<<< network')

        # add report
        report.append('# path=app.coverage.txt')
        report.append('/file:\n 1 | 1|line')

        if 'm' in keys:
            report.append('<<<<<< EOF')
            report.append('# path=app.coverage.txt')
            report.append('/file2:\n 1 | 1|line')

        if 'M' in keys:
            master = self.get_v3_report()
        else:
            master = None

        master = process.process_raw_upload(commit_yaml=None,
                                            original_report=master,
                                            reports='\n'.join(report),
                                            flags=[])

        if 'e' in keys:
            assert master.sessions[0].env == {'A': 'b'}
        else:
            if 'M' in keys:
                assert master.sessions[3].totals == ReportTotals(files=1, lines=1, hits=1, misses=0, partials=0, coverage='100', branches=0, methods=0, messages=0, sessions=0)

        if 'M' in keys:
            assert master.totals.files == 7 + (1 if ('m' in keys and 'n' not in keys) else 0)
            assert master.totals.sessions == 4
        else:
            assert master.totals.files == 1 + (1 if ('m' in keys and 'n' not in keys) else 0)
            assert master.totals.sessions == 1

        if 'n' in keys:
            assert master.get('path/to/file')
            assert master['path/to/file'][1].coverage == 1
        else:
            assert master.get('file')
            assert master['file'][1].coverage == 1
        assert ('file2' in master) is ('m' in keys and 'n' not in keys)

    def test_none(self):
        with pytest.raises(AssertionError, match='No files found in report.'):
            process.process_raw_upload(self, {}, '', [])


class TestProcessRawUploadFixed(BaseTestCase):
    def test_fixes(self):
        reports = '\n'.join(('# path=coverage.info',
                             'mode: count',
                             'file.go:7.14,9.2 1 1',
                             '<<<<<< EOF',
                             '# path=fixes',
                             'file.go:8:',
                             '<<<<<< EOF', ''))
        report = process.process_raw_upload(commit_yaml={}, original_report=None, reports=reports, flags=[], session={})
        assert 2 not in report['file.go'], '2 never existed'
        assert report['file.go'][7].coverage == 1
        assert 8 not in report['file.go'], '8 should have been removed'
        assert 9 not in report['file.go'], '9 should have been removed'


class TestProcessRawUploadNotJoined(BaseTestCase):
    @pytest.mark.parametrize('flag, joined', [('nightly', False), ('unittests', True), ('ui', True), ('other', True)])
    def test_not_joined(self, flag, joined):
        yaml = {
            'flags': {
                'nightly': {'joined': False},
                'unittests': {'joined': True},
                'ui': {
                    'paths': ['ui/']
                }
            }
        }
        merge = Mock(side_effect=NotImplementedError)
        report = Mock(totals=Mock())
        with patch('services.report.raw_upload_processor.process_report', return_value=report):
            with pytest.raises(NotImplementedError):
                report = process.process_raw_upload(
                    commit_yaml=yaml,
                    original_report=Mock(
                        merge=merge,
                        add_session=Mock(return_value=(1, Session()))),
                    reports='a<<<<<< EOF',
                    flags=[flag],
                    session=Session())
            merge.assert_called_with(report, joined=joined)


class TestProcessRawUploadFlags(BaseTestCase):
    @pytest.mark.parametrize('flag', [{'paths': ['!tests/.*']},
           {'ignore': ['tests/.*']},
           {'paths': ['folder/']}])
    def test_flags(self, flag):
        master = process.process_raw_upload(commit_yaml={'flags': {'docker': flag}},
                                            original_report={},
                                            session={},
                                            reports='{"coverage": {"tests/test.py": [null, 0], "folder/file.py": [null, 1]}}',
                                            flags=['docker'])
        assert master.files == ['folder/file.py']
        assert master.sessions[0].flags == ['docker']


class TestProcessSessions(BaseTestCase):
    def test_sessions(self):
        master = process.process_raw_upload(commit_yaml={},
                                            original_report={}, session={},
                                            reports='{"coverage": {"tests/test.py": [null, 0], "folder/file.py": [null, 1]}}',
                                            flags=None)
        master = process.process_raw_upload(commit_yaml={},
                                            original_report=master, session={},
                                            reports='{"coverage": {"tests/test.py": [null, 0], "folder/file.py": [null, 1]}}',
                                            flags=None)
        print(master.totals)
        assert master.totals.sessions == 2


class TestProcessReport(BaseTestCase):
    @pytest.mark.parametrize("report", ["<idk>", "<?xml", "# path=./coverage.xml\n\n"])
    def test_emptys(self, report):
        res = process.process_report(report=report,
                                     commit_yaml=None,
                                     sessionid=0,
                                     ignored_lines={},
                                     path_fixer=str)

        assert res is None

    def test_fixes_paths(self):
        res = process.process_report(report='# path=app.coverage.txt\n/file:\n 1 | 1|line',
                                     commit_yaml=None,
                                     sessionid=0,
                                     ignored_lines={},
                                     path_fixer=str)

        assert res.get('file') is not None

    @pytest.mark.parametrize("lang, report", [('go.from_txt', 'mode: atomic'),
           ('xcode.from_txt', '# path=/Users/path/to/app.coverage.txt\n<data>'),
           ('xcode.from_txt', '# path=app.coverage.txt\n<data>'),
           ('xcode.from_txt', '# path=/Users/path/to/framework.coverage.txt\n<data>'),
           ('xcode.from_txt', '# path=framework.coverage.txt\n<data>'),
           ('xcode.from_txt', '# path=/Users/path/to/xctest.coverage.txt\n<data>'),
           ('xcode.from_txt', '# path=xctest.coverage.txt\n<data>'),
           ('xcode.from_txt', '# path=coverage.txt\n/blah/app.h:\n'),
           ('dlst.from_string', 'data\ncovered'),
           ('vb.from_xml', '<results><SampleTag></SampleTag></results>'),
           ('lcov.from_txt', '\nend_of_record'),
           ('gcov.from_txt', '0:Source:\nline2'),
           ('lua.from_txt', '======='),
           ('gap.from_string', '{"Type": "S", "File": "a"}'),
           ('v1.from_json', '{"RSpec": {"coverage": {}}}'),
           ('v1.from_json', '{"MiniTest": {"coverage": {}}}'),
           ('v1.from_json', '{"coverage": {}}'),
           ('v1.from_json', '{"coverage": {"data": "'+u'\xf1'+'"}}'),  # non-acii
           ('rlang.from_json', '{"uploader": "R"}'),
           ('scala.from_json', '{"fileReports": ""}'),
           ('coveralls.from_json', '{"source_files": ""}'),
           ('node.from_json', '{"branchMap": ""}'),
           ('scoverage.from_xml', '<statements><data>'+u'\xf1'+'</data></statements>'),
           ('clover.from_xml', '<coverage generated="abc"><SampleTag></SampleTag></coverage>'),
           ('cobertura.from_xml', '<coverage><SampleTag></SampleTag></coverage>'),
           ('csharp.from_xml', '<CoverageSession><SampleTag></SampleTag></CoverageSession>'),
           ('jacoco.from_xml', '<report><SampleTag></SampleTag></report>'),
           ('xcodeplist.from_xml', '<?xml version="1.0">\n<plist version="1.0">'),
           ('xcodeplist.from_xml', '# path=3CB41F9A-1DEA-4DE1-B321-6F462C460DB6.xccoverage.plist\n__'),
           ('scoverage.from_xml', '<?xml version="1.0" encoding="utf-8"?>\n<statements><SampleTag></SampleTag></statements>'),
           ('clover.from_xml', '<?xml version="1.0" encoding="utf-8"?>\n<coverage generated="abc"><SampleTag></SampleTag></coverage>'),
           ('cobertura.from_xml', '<?xml version="1.0" encoding="utf-8"?>\n<coverage><SampleTag></SampleTag></coverage>'),
           ('csharp.from_xml', '<?xml version="1.0" encoding="utf-8"?>\n<CoverageSession><SampleTag></SampleTag></CoverageSession>'),
           ('jacoco.from_xml', '<?xml version="1.0" encoding="utf-8"?>\n<report><SampleTag></SampleTag></report>')])
    def test_detect(self, lang, report):
        with patch('services.report.languages.%s' % lang, return_value=lang) as func:
            res = process.process_report(report=report,
                                         commit_yaml=None,
                                         sessionid=0,
                                         ignored_lines={},
                                         path_fixer=str)
            assert res == lang
            assert func.called

    def test_xxe_entity_not_called(self):
        report_xxe_xml = """<?xml version="1.0"?>
        <!DOCTYPE coverage [
        <!ELEMENT coverage ANY >
        <!ENTITY xxe SYSTEM "file:///config/codecov.yml" >]>
        <statements><statement>&xxe;</statement></statements>
        """
        with patch('services.report.languages.scoverage.from_xml') as func:
            process.process_report(
                report=report_xxe_xml,
                commit_yaml=None,
                sessionid=0,
                ignored_lines={},
                path_fixer=str
            )
            assert func.called
            expected_xml_string = '<statements><statement>&xxe;</statement></statements>'
            output_xml_string = etree.tostring(func.call_args_list[0][0][0]).decode()
            assert output_xml_string == expected_xml_string
