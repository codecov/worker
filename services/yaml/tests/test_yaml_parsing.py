from pathlib import Path

import pytest

from tests.base import BaseTestCase
from services.yaml.parser import parse_yaml_file
from services.yaml.exceptions import InvalidYamlException

here = Path(__file__)


class TestYamlSavingService(BaseTestCase):

    def test_parse_empty_yaml(self):
        contents = ""
        res = parse_yaml_file(contents)
        assert res is None

    def test_parse_invalid_yaml(self):
        contents = "invalid: aaa : bbb"
        with pytest.raises(InvalidYamlException):
            parse_yaml_file(contents)

    def test_parse_simple_yaml(self):
        with open(here.parent / 'samples' / 'sample_yaml_1.yaml') as f:
            contents = f.read()
        res = parse_yaml_file(contents)
        expected_result = {
            'coverage': {
                'precision': 2,
                'round': 'down',
                'range': "70...100",
                'status': {
                    'project': True,
                    'patch': True,
                    'changes': False,
                }
            },
            'codecov': {
                'notify': {
                    'require_ci_to_pass': True
                }
            },
            'comment': {
                'behavior': 'default',
                'layout': 'header, diff',
                'require_changes': False
            },
            'parsers': {
                'gcov': {
                    'branch_detection': {
                        'conditional': True,
                        'loop': True,
                        'macro': False,
                        'method': False
                    }
                }
            }
        }
        assert res == expected_result
