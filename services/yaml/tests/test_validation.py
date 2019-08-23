import re

import pytest
from schema import SchemaError

from tests.base import BaseTestCase
from services.yaml.validation import LayoutStructure, validate_yaml, PathStructure


class TestPathStructure(BaseTestCase):

    def test_simple_path_structure_no_star(self):
        ps = PathStructure()
        res = ps.validate('a/b')
        compiled = re.compile(res)
        assert compiled.match('a/b') is not None
        assert compiled.match('a/b/file_1.py') is not None
        assert compiled.match('c/a/b') is None
        assert compiled.match('a/path/b') is None
        assert compiled.match('a/path/path2/b') is None

    def test_simple_path_structure_one_star(self):
        ps = PathStructure()
        res = ps.validate('a/*/b')
        compiled = re.compile(res)
        assert compiled.match('a/path/b') is not None
        assert compiled.match('a/path/b/file_2.py') is not None
        assert compiled.match('a/path/b/more_path/some_file.py') is not None
        assert compiled.match('a/b') is None
        assert compiled.match('a/path/path2/b') is None

    def test_simple_path_structure_negative(self):
        ps = PathStructure()
        res = ps.validate('!path/to/folder')
        assert res.startswith('!')
        compiled = re.compile(res[1:])
        # Check the negatives, we want `path/to/folder` files to match so we refuse them later
        assert compiled.match('path/to/folder') is not None
        assert compiled.match('path/to/folder/file_2.py') is not None
        assert compiled.match('path/to/folder/more_path/some_file.py') is not None
        assert compiled.match('a/b') is None
        assert compiled.match('path/folder') is None

    def test_simple_path_structure_double_star(self):
        ps = PathStructure()
        res = ps.validate('a/**/b')
        compiled = re.compile(res)
        assert compiled.match('a/path/b') is not None
        assert compiled.match('a/path/b/some_file.py') is not None
        assert compiled.match('a/path/b/more_path/some_file.py') is not None
        assert compiled.match('a/path/path2/b') is not None
        assert compiled.match('a/path/path2/b/some_file.py') is not None
        assert compiled.match('a/path/path2/b/more_path/some_file.py') is not None
        assert compiled.match('a/c') is None

    def test_multiple_path_structures(self):
        ps = PathStructure()
        # assert ps.validate('**/abc') == '^.*/abc.*'
        # assert ps.validate('**/**/abc') == '^.*/.*/abc.*'
        # assert ps.validate('**/**/abc**') == '^.*/.*/abc.*'
        # assert ps.validate('*/abc') == '^.*/abc.*'
        # assert ps.validate('folder') == '^folder.*'
        # assert ps.validate('/folder') == '^folder.*'
        # assert ps.validate('./folder') == '^folder.*'
        # assert ps.validate('folder/') == '^folder/.*'
        # assert ps.validate('!/folder/') == '!^folder/.*'
        # assert ps.validate('!^/folder/') == '!^folder/.*'
        # assert ps.validate('!^/folder/$') == '!^folder/$'
        # assert ps.validate('!^/folder/file.py$') == '!^folder/file.py$'
        # assert ps.validate('^/folder/file.py$') == '^folder/file.py$'
        # assert ps.validate('/folder/file.py$') == '^folder/file.py$'
        # assert ps.validate('path/**/') == '^path/.*/.*'


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
