import re

import pytest
from schema import SchemaError

from tests.base import BaseTestCase
from services.yaml.validation import (
    LayoutStructure, validate_yaml, PathPatternSchemaField, CoverageRangeSchemaField,
    PercentSchemaField, CustomFixPathSchemaField, pre_process_yaml
)
from services.yaml.exceptions import InvalidYamlException
from services.yaml.validation.helpers import (
    determine_path_pattern_type, translate_glob_to_regex
)
from services.report.fixpaths import fixpaths_to_func


class TestPathPatternSchemaField(BaseTestCase):

    def test_simple_path_structure_no_star(self):
        ps = PathPatternSchemaField()
        res = ps.validate('a/b')
        compiled = re.compile(res)
        assert compiled.match('a/b') is not None
        assert compiled.match('a/b/file_1.py') is not None
        assert compiled.match('c/a/b') is None
        assert compiled.match('a/path/b') is None
        assert compiled.match('a/path/path2/b') is None

    def test_simple_path_structure_regex(self):
        ps = PathPatternSchemaField()
        res = ps.validate('[a-z]+/test_.*')
        compiled = re.compile(res)
        assert compiled.match('perro/test_folder.py') is not None
        assert compiled.match('cachorro/test_folder.py') is not None
        assert compiled.match('cachorro/tes_folder.py') is None
        assert compiled.match('cachorro/what/test_folder.py') is None
        assert compiled.match('[/a/b') is None

    def test_simple_path_structure_one_star_end(self):
        ps = PathPatternSchemaField()
        res = ps.validate('tests/*')
        compiled = re.compile(res)
        assert compiled.match('tests/file_1.py') is not None
        assert compiled.match('tests/testeststsetetesetsfile_2.py') is not None
        assert compiled.match('tests/deep/file_1.py') is None

    def test_simple_path_structure_one_star(self):
        ps = PathPatternSchemaField()
        res = ps.validate('a/*/b')
        compiled = re.compile(res)
        assert compiled.match('a/path/b') is not None
        assert compiled.match('a/path/b/file_2.py') is not None
        assert compiled.match('a/path/b/more_path/some_file.py') is not None
        assert compiled.match('a/b') is None
        assert compiled.match('a/path/path2/b') is None

    def test_simple_path_structure_negative(self):
        ps = PathPatternSchemaField()
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
        ps = PathPatternSchemaField()
        res = ps.validate('a/**/b')
        compiled = re.compile(res)
        assert compiled.match('a/path/b') is not None
        assert compiled.match('a/path/b/some_file.py') is not None
        assert compiled.match('a/path/b/more_path/some_file.py') is not None
        assert compiled.match('a/path/path2/b') is not None
        assert compiled.match('a/path/path2/b/some_file.py') is not None
        assert compiled.match('a/path/path2/b/more_path/some_file.py') is not None
        assert compiled.match('a/c') is None

    def test_path_with_leading_period_slash(self):
        ps = PathPatternSchemaField()
        res = ps.validate('./src/register-test-globals.ts')
        compiled = re.compile(res)
        assert compiled.match('src/register-test-globals.ts') is not None
        second_res = ps.validate("./test/*.cc")
        second_compiled = re.compile(second_res)
        assert second_compiled.match('test/test_SW_Markov.cc') is not None

    def test_star_dot_star_pattern(self):
        ps = PathPatternSchemaField()
        res = ps.validate("test/**/*.*")
        compiled = re.compile(res)
        assert compiled.match('test/unit/presenters/goal_sparkline_test.rb') is not None

    def test_double_star_end(self):
        user_input = "Snapshots/**"
        ps = PathPatternSchemaField()
        res = ps.validate(user_input)
        compiled = re.compile(res)
        assert compiled.match('Snapshots/Snapshots/ViewController.swift') is not None


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


class TestCoverageRangeSchemaField(BaseTestCase):

    def test_simple_coverage_range(self):
        crsf = CoverageRangeSchemaField()
        assert crsf.validate([80, 90]) == [80.0, 90.0]
        assert crsf.validate('80..90') == [80.0, 90.0]
        assert crsf.validate('80...90') == [80.0, 90.0]
        assert crsf.validate('80...100') == [80.0, 100.0]
        invalid_cases = [
            '80....90',
            '80.90',
            '90..80',
            '90..80..50',
            'infinity...90',
            '80...?90',
            '80...101',
            '-80...90',
            '80...9f0',
            ['arroba', 90],
            [10, 20, 30],
            [10, 20, 30],
            ['infinity', 90]
        ]
        for invalid in invalid_cases:
            with pytest.raises(SchemaError):
                crsf.validate(invalid)


class TestPercentSchemaField(BaseTestCase):

    def test_simple_coverage_range(self):
        crsf = PercentSchemaField()
        assert crsf.validate(80) == 80.0
        assert crsf.validate(80.0) == 80.0
        assert crsf.validate('80%') == 80.0
        assert crsf.validate('80') == 80.0
        assert crsf.validate('0') == 0.0
        assert crsf.validate('150%') == 150.0
        with pytest.raises(SchemaError):
            crsf.validate('nana')
        with pytest.raises(SchemaError):
            crsf.validate('%80')
        with pytest.raises(SchemaError):
            crsf.validate('8%0%')
        with pytest.raises(SchemaError):
            crsf.validate('infinity')
        with pytest.raises(SchemaError):
            crsf.validate('nan')


class TestPatternTypeDetermination(BaseTestCase):

    def test_determine_path_pattern_type(self):
        assert determine_path_pattern_type('path/to/folder') == 'path_prefix'
        assert determine_path_pattern_type('path/*/folder') == 'glob'
        assert determine_path_pattern_type('path/**/folder') == 'glob'
        assert determine_path_pattern_type('path/.*/folder') == 'regex'
        assert determine_path_pattern_type('path/[a-z]*/folder') == 'regex'
        assert determine_path_pattern_type('*/[a-z]*/folder') == 'glob'
        assert determine_path_pattern_type("before/test-*::after/") == 'glob'


class TestPreprocess(BaseTestCase):

    def test_preprocess_empty(self):
        user_input = {}
        expected_result = {}
        pre_process_yaml(user_input)
        assert expected_result == user_input

    def test_preprocess_none_in_fields(self):
        user_input = {'codecov': None}
        expected_result = {'codecov': None}
        pre_process_yaml(user_input)
        assert expected_result == user_input


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
                'range': [70, 100],
                'status': {
                    'project': True,
                    'patch': True,
                    'changes': False,
                }
            },
            'codecov': {
                'notify': {},
                'require_ci_to_pass': True
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

    def test_invalid_yaml_case(self):
        user_input = {
            "coverage": {
                "round": "down",
                "precision": 2,
                "range": "70...100",
                "status": {
                    "project": {
                        "base": "auto",
                        "aa": True
                    }
                }
            },
            "ignore": [
                "Pods/.*",
            ]
        }
        with pytest.raises(InvalidYamlException) as exc:
            validate_yaml(user_input)
        assert exc.value.error_location == 'Path: coverage->status->project->base'

    def test_yaml_with_status_case(self):
        user_input = {
            "coverage": {
                "round": "down",
                "precision": 2,
                "range": "70...100",
                "status": {
                    "project": {
                        "default": {
                            "base": "auto",
                        }
                    }
                }
            },
            "ignore": [
                "Pods/.*",
            ]
        }
        expected_result = {
            "coverage": {
                "round": "down",
                "precision": 2,
                "range": [70.0, 100.0],
                "status": {
                    "project": {
                        "default": {
                            "base": "auto",
                        }
                    }
                }
            },
            "ignore": [
                "Pods/.*",
            ]
        }
        result = validate_yaml(user_input)
        assert result == expected_result


class TestGlobToRegexTranslation(BaseTestCase):

    def test_translate_glob_to_regex(self):
        assert re.compile(translate_glob_to_regex('a')).match('a') is not None
        assert re.compile(translate_glob_to_regex('[abc]*')).match('a') is None
        assert re.compile(translate_glob_to_regex('[abc]*')).match('ab') is not None
        assert re.compile(translate_glob_to_regex('[abc]')).match('d') is None
        assert re.compile(translate_glob_to_regex('[a-c]')).match('b') is not None


class TestCustomFixPathSchemaField(BaseTestCase):

    def test_custom_fixpath(self):
        cfpsf = CustomFixPathSchemaField()
        res = cfpsf.validate('a::b')
        processing_func = fixpaths_to_func([res])
        assert processing_func('a/this_love/has/taken.py') == 'b/this_love/has/taken.py'
        assert processing_func('b/this_love/has/taken.py') == 'b/this_love/has/taken.py'
        assert processing_func('b/a/this_love/has/taken.py') == 'b/a/this_love/has/taken.py'

    def test_custom_fixpath_removal(self):
        cfpsf = CustomFixPathSchemaField()
        res = cfpsf.validate('a/::')
        processing_func = fixpaths_to_func([res])
        assert processing_func('a/this_love/has/taken.py') == 'this_love/has/taken.py'
        assert processing_func('b/this_love/has/taken.py') == 'b/this_love/has/taken.py'
        assert processing_func('b/a/this_love/has/taken.py') == 'b/a/this_love/has/taken.py'

    def test_custom_fixpath_removal_no_slashes(self):
        cfpsf = CustomFixPathSchemaField()
        res = cfpsf.validate('a::')
        processing_func = fixpaths_to_func([res])
        assert processing_func('a/this_love/has/taken.py') == 'this_love/has/taken.py'
        assert processing_func('b/this_love/has/taken.py') == 'b/this_love/has/taken.py'
        assert processing_func('b/a/this_love/has/taken.py') == 'b/a/this_love/has/taken.py'

    def test_custom_fixpath_addition(self):
        cfpsf = CustomFixPathSchemaField()
        res = cfpsf.validate('::b')
        processing_func = fixpaths_to_func([res])
        assert processing_func('a/this_love/has/taken.py') == 'b/a/this_love/has/taken.py'
        assert processing_func('b/this_love/has/taken.py') == 'b/b/this_love/has/taken.py'
        assert processing_func('b/a/this_love/has/taken.py') == 'b/b/a/this_love/has/taken.py'

    def test_custom_fixpath_regex(self):
        cfpsf = CustomFixPathSchemaField()
        res = cfpsf.validate('path-*::b')
        print(res)
        processing_func = fixpaths_to_func([res])
        assert processing_func('path/this_love/has/taken.py') == 'path/this_love/has/taken.py'
        assert processing_func('path-puppy/this_love/has/taken.py') == 'b/this_love/has/taken.py'
        assert processing_func('path-monster/this_love/has/taken.py') == 'b/this_love/has/taken.py'
        assert processing_func('b/this_love/has/taken.py') == 'b/this_love/has/taken.py'
        assert processing_func('b/a/this_love/has/taken.py') == 'b/a/this_love/has/taken.py'

    def test_custom_fixpath_docs_example(self):
        cfpsf = CustomFixPathSchemaField()
        res = cfpsf.validate("before/tests-*::after/")
        processing_func = fixpaths_to_func([res])
        assert processing_func('before/tests-apples/test.js') == 'after/test.js'
        assert processing_func('before/tests-oranges/test.js') == 'after/test.js'
        assert processing_func('before/app-apples/app.js') == 'before/app-apples/app.js'
        assert processing_func('unrelated/path/taken.py') == 'unrelated/path/taken.py'
