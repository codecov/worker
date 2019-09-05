from tests.base import BaseTestCase
from services.yaml import get_final_yaml


class TestYamlService(BaseTestCase):

    def test_get_final_yaml_no_yaml_no_config_yaml(self, mock_configuration):
        expected_result = {}
        result = get_final_yaml(
            owner_yaml=None,
            repo_yaml=None,
            commit_yaml=None
        )
        assert expected_result == result

    def test_get_final_yaml_empty_yaml_no_config_yaml(self, mock_configuration):
        expected_result = {}
        result = get_final_yaml(
            owner_yaml={},
            repo_yaml={},
            commit_yaml={}
        )
        assert expected_result == result

    def test_get_final_yaml_no_yaml(self, mock_configuration):
        mock_configuration.set_params({
            'site': {
                'coverage': {
                    'precision': 2.0
                },
                'parsers': {
                    'gcov': {
                        'branch_detection': {
                            'conditional': True
                        }
                    }
                }
            }
        })
        expected_result = {
            'coverage': {
                'precision': 2.0
            },
            'parsers': {
                'gcov': {
                    'branch_detection': {
                        'conditional': True
                    }
                }
            }
        }
        result = get_final_yaml(
            owner_yaml={},
            repo_yaml={},
            commit_yaml={}
        )
        assert expected_result == result

    def test_get_final_yaml_owner_yaml(self, mock_configuration):
        mock_configuration.set_params({
            'site': {
                'coverage': {
                    'precision': 2.0
                },
                'parsers': {
                    'gcov': {
                        'branch_detection': {
                            'conditional': True
                        }
                    }
                }
            }
        })
        expected_result = {
            'coverage': {
                'precision': 2.0
            },
            'parsers': {
                'gcov': {
                    'branch_detection': {
                        'conditional': True
                    }
                },
                'new_language': 'damn right'
            }
        }
        result = get_final_yaml(
            owner_yaml={'parsers': {'new_language': 'damn right'}},
            repo_yaml={},
            commit_yaml={}
        )
        assert expected_result == result

    def test_get_final_yaml_both_repo_and_commit_yaml(self, mock_configuration):
        mock_configuration.set_params({
            'site': {
                'coverage': {
                    'precision': 2.0
                },
                'parsers': {
                    'gcov': {
                        'branch_detection': {
                            'conditional': True
                        }
                    }
                }
            }
        })
        expected_result = {
            'coverage': {
                'precision': 2.0
            },
            'parsers': {
                'gcov': {
                    'branch_detection': {
                        'conditional': True
                    }
                },
                'different_language': 'say what'
            }
        }
        result = get_final_yaml(
            owner_yaml=None,
            repo_yaml={'parsers': {'new_language': 'damn right'}},
            commit_yaml={'parsers': {'different_language': 'say what'}}
        )
        assert expected_result == result
