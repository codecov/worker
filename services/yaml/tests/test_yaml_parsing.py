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
                'range': (70.0, 100.0),
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

    def test_parse_big_yaml_file(self):
        with open(here.parent / 'samples' / 'big.yaml') as f:
            contents = f.read()
        res = parse_yaml_file(contents)
        expected_result = {
            'comment': {
                'branches': ['.*'],
                'layout': 'diff, flags, reach', 'behavior': 'default'
            },
            'ignore': ['^tests/.*'],
            'flags': {
                'integration': {
                    'ignore': ['^app/ui.*'], 'branches': ['master']
                }
            },
            'codecov': {
                'ci': ['ci.domain.com', '!provider'], 'url': 'http://codecov.io', 'bot': 'username',
                'token': 'uuid', 'notify': {'countdown': 12, 'after_n_builds': 2, 'delay': 4},
                'branch': 'master', 'slug': 'owner/repo', 'require_ci_to_pass': True
            },
            'coverage': {
                'status': {
                    'project': {
                        'default': {
                            'if_ci_failed': 'error', 'only_pulls': False, 'branches': ['^master$'],
                            'target': 'auto', 'paths': ['^folder.*'], 'against': 'parent',
                            'flags': ['integration'], 'if_not_found': 'success',
                            'if_no_uploads': 'error', 'threshold': 1.0
                        }
                    },
                    'changes': {
                        'default': {
                            'if_ci_failed': 'error', 'only_pulls': False, 'branches': None,
                            'paths': ['^folder.*'], 'against': 'parent', 'flags': ['integration'],
                            'if_not_found': 'success', 'if_no_uploads': 'error'
                        }
                    },
                    'patch': {
                        'default': {
                            'if_ci_failed': 'error', 'only_pulls': False, 'branches': None,
                            'target': 80.0, 'paths': ['^folder.*'], 'against': 'parent',
                            'flags': ['integration'], 'if_not_found': 'success',
                            'if_no_uploads': 'success'
                        }
                    }
                },
                'range': [50.0, 60.0], 'precision': 2,
                'round': 'down',
                'notify': {
                    'slack': {
                        'default': {
                            'only_pulls': False, 'branches': None, 'attachments': 'sunburst, diff',
                            'paths': None, 'url': 'http://uol', 'flags': None, 'threshold': 1.0,
                            'message': 'Coverage {{changed}} for {{owner}}/{{repo}}'
                        }
                    },
                    'hipchat': {
                        'default': {
                            'paths': None, 'branches': None, 'room': 'name|id', 'url': 'http://uol',
                            'token': 'encrypted', 'flags': None, 'notify': False, 'threshold': 1.0,
                            'message': 'Coverage {{changed}} for {{owner}}/{{repo}}'
                        }
                    },
                    'irc': {
                        'default': {
                            'paths': None, 'branches': None, 'threshold': 1.0, 'flags': None,
                            'message': 'Coverage {{changed}} for {{owner}}/{{repo}}', 'server':
                            'chat.freenode.net'
                        }
                    },
                    'webhook': {
                        '_name_': {
                            'url': 'http://uol', 'threshold': 1.0, 'branches': None
                        }
                    },
                    'email': {
                        'default': {
                            'paths': None, 'only_pulls': False, 'layout': 'reach, diff, flags',
                            'to': ['example@domain.com', "secondexample@seconddomain.com"],
                            'threshold': 1.0, 'flags': None
                        }
                    },
                    'gitter': {
                        'default': {
                            'url': 'http://uol', 'threshold': 1.0,
                            'message': 'Coverage {{changed}} for {{owner}}/{{repo}}',
                            'branches': None
                        }
                    }
                }
            },
            'fixes': ['^old_path::new_path']
        }
        for key in res.keys():
            assert sorted(res.get(key).items()) == sorted(expected_result.get(key).items())
        assert sorted(res.items()) == sorted(expected_result.items())
        assert res == expected_result
