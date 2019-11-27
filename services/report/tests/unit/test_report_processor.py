import json

from services.report.report_processor import report_type_matching


class TestReportTypeMatching(object):

    def test_report_type_matching(self):
        assert report_type_matching('name', '')[1] == 'txt'
        assert report_type_matching('name', json.dumps({'value': 1}))[1] == 'json'
        assert report_type_matching('name', '<?xml version="1.0" ?><statements><statement>source.scala</statement></statements>')[1] == 'xml'
        assert report_type_matching('name', '\uFEFF<?xml version="1.0" ?><statements><statement>source.scala</statement></statements>')[1] == 'xml'
        assert report_type_matching('name', 'normal file')[1] == 'txt'
