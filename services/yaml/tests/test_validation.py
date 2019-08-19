import pytest
from schema import SchemaError

from tests.base import BaseTestCase
from services.yaml.validation import LayoutStructure, validate_yaml


class TestLayoutStructure(BaseTestCase):

    def test_simple_layout(self):
        schema = LayoutStructure()
        result = "reach, diff, flags, files, footer"
        expected_result = 'reach, diff, flags, files, footer'
        assert expected_result == schema.validate(result)

    def test_simple_layout_bad_name(self):
        schema = LayoutStructure()
        result = "reach, diff, flags, love, files, footer"
        with pytest.raises(SchemaError) as exc:
            schema.validate(result)
        assert exc.value.code == "Unexpected values on layout: love"


class TestUserYamlValidation(BaseTestCase):

    def test_empty_case(self):
        user_input = {}
        expected_result = {}
        assert validate_yaml(user_input) == expected_result

    def test_simple_case(self):
        user_input = {
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
        expected_result = {
            'coverage': {
                'precision': 2,
                'round': 'down',
                'range': (70, 100),
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
        assert validate_yaml(user_input) == expected_result
