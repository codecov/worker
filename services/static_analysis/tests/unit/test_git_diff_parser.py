from services.static_analysis.git_diff_parser import (
    DiffChange,
    DiffChangeType,
    parse_git_diff_json,
)


class TestDiffChange(object):
    def test_line_mapping_modified_file(self):
        sample_git_diff_change = DiffChange(
            before_filepath="README.rst",
            after_filepath="README.rst",
            change_type=DiffChangeType.modified,
            lines_only_on_base=[12, 49, 153, 154],
            lines_only_on_head=[12, 13, 50, 56, 57, 58, 59, 60, 61, 62, 161],
        )
        # base to head
        assert sample_git_diff_change.map_base_line_to_head_line(1) == 1
        assert sample_git_diff_change.map_base_line_to_head_line(11) == 11
        assert sample_git_diff_change.map_base_line_to_head_line(12) is None
        assert sample_git_diff_change.map_base_line_to_head_line(13) == 14
        assert sample_git_diff_change.map_base_line_to_head_line(48) == 49
        assert sample_git_diff_change.map_base_line_to_head_line(49) is None
        assert sample_git_diff_change.map_base_line_to_head_line(50) == 51
        # head to base
        assert sample_git_diff_change.map_head_line_to_base_line(1) == 1
        assert sample_git_diff_change.map_head_line_to_base_line(11) == 11
        assert sample_git_diff_change.map_head_line_to_base_line(12) is None
        assert sample_git_diff_change.map_head_line_to_base_line(13) is None
        assert sample_git_diff_change.map_head_line_to_base_line(14) == 13
        assert sample_git_diff_change.map_head_line_to_base_line(49) == 48
        assert sample_git_diff_change.map_head_line_to_base_line(50) is None
        assert sample_git_diff_change.map_head_line_to_base_line(51) == 50
        # next one is reasonable because there is 7 more head lines than base lines
        assert sample_git_diff_change.map_head_line_to_base_line(1000) == 993
        assert sample_git_diff_change.map_base_line_to_head_line(993) == 1000

    def test_line_mapping_deleted_file(self):
        sample_git_diff_change = DiffChange(
            before_filepath="README.rst",
            after_filepath="README.rst",
            change_type=DiffChangeType.deleted,
            lines_only_on_base=None,
            lines_only_on_head=None,
        )
        assert sample_git_diff_change.map_head_line_to_base_line(1) is None

    def test_line_mapping_binary_file(self):
        sample_git_diff_change = DiffChange(
            before_filepath="README.rst",
            after_filepath="README.rst",
            change_type=DiffChangeType.binary,
            lines_only_on_base=None,
            lines_only_on_head=None,
        )
        assert sample_git_diff_change.map_head_line_to_base_line(1) is None

    def test_line_mapping_new_file(self):
        sample_git_diff_change = DiffChange(
            before_filepath="README.rst",
            after_filepath="README.rst",
            change_type=DiffChangeType.new,
            lines_only_on_base=None,
            lines_only_on_head=None,
        )
        assert sample_git_diff_change.map_head_line_to_base_line(1) is None


class TestParseGitDiffJson(object):
    def test_parse_git_diff_json_single_file(self):
        input_data = {
            "diff": {
                "files": {
                    "README.rst": {
                        "type": "modified",
                        "before": None,
                        "segments": [
                            {
                                "header": ["9", "7", "9", "8"],
                                "lines": [
                                    " Overview",
                                    " --------",
                                    " ",
                                    "-Main website: `Codecov <https://codecov.io/>`_.",
                                    "+",
                                    "+website: `Codecov <https://codecov.io/>`_.",
                                    " ",
                                    " .. code-block:: shell-session",
                                    " ",
                                ],
                            },
                            {
                                "header": ["46", "12", "47", "19"],
                                "lines": [
                                    " ",
                                    " You may need to configure a ``.coveragerc`` file. Learn more `here <http://coverage.readthedocs.org/en/latest/config.html>`_. Start with this `generic .coveragerc <https://gist.github.com/codecov-io/bf15bde2c7db1a011b6e>`_ for example.",
                                    " ",
                                    "-We highly suggest adding `source` to your ``.coveragerc`` which solves a number of issues collecting coverage.",
                                    "+We highly suggest adding ``source`` to your ``.coveragerc``, which solves a number of issues collecting coverage.",
                                    " ",
                                    " .. code-block:: ini",
                                    " ",
                                    "    [run]",
                                    "    source=your_package_name",
                                    "+   ",
                                    "+If there are multiple sources, you instead should add ``include`` to your ``.coveragerc``",
                                    "+",
                                    "+.. code-block:: ini",
                                    "+",
                                    "+   [run]",
                                    "+   include=your_package_name/*",
                                    " ",
                                    " unittests",
                                    " ---------",
                                ],
                            },
                            {
                                "header": ["150", "5", "158", "4"],
                                "lines": [
                                    " * Twitter: `@codecov <https://twitter.com/codecov>`_.",
                                    " * Email: `hello@codecov.io <hello@codecov.io>`_.",
                                    " ",
                                    "-We are happy to help if you have any questions. Please contact email our Support at [support@codecov.io](mailto:support@codecov.io)",
                                    "-",
                                    "+We are happy to help if you have any questions. Please contact email our Support at `support@codecov.io <mailto:support@codecov.io>`_.",
                                ],
                            },
                        ],
                        "stats": {"added": 11, "removed": 4},
                    }
                }
            },
        }
        res = list(parse_git_diff_json(input_data))
        assert res == [
            DiffChange(
                before_filepath="README.rst",
                after_filepath="README.rst",
                change_type=DiffChangeType.modified,
                lines_only_on_base=[12, 49, 153, 154],
                lines_only_on_head=[12, 13, 50, 56, 57, 58, 59, 60, 61, 62, 161],
            )
        ]

    def test_parse_git_diff_json_multiple_files(self):
        input_data = {
            "files": {
                "banana.py": {
                    "type": "new",
                    "before": None,
                    "segments": [
                        {
                            "header": ["0", "0", "1", "2"],
                            "lines": ["+suhduad", "+dsandsa"],
                        }
                    ],
                    "stats": {"added": 2, "removed": 0},
                },
                "codecov-alpine": {
                    "type": "binary",
                    "stats": {"added": 0, "removed": 0},
                },
                "codecov/settings_dev.py": {
                    "type": "modified",
                    "before": None,
                    "segments": [
                        {
                            "header": ["49", "3", "49", "4"],
                            "lines": [
                                ' SESSION_COOKIE_DOMAIN = "localhost"',
                                " ",
                                " GRAPHQL_PLAYGROUND = True",
                                "+IS_DEV = True",
                            ],
                        }
                    ],
                    "stats": {"added": 1, "removed": 0},
                },
                "production.yml": {
                    "type": "deleted",
                    "before": "production.yml",
                    "stats": {"added": 0, "removed": 0},
                },
            }
        }
        expected_result = [
            DiffChange(
                before_filepath=None,
                after_filepath="banana.py",
                change_type=DiffChangeType.new,
                lines_only_on_base=[],
                lines_only_on_head=[1, 2],
            ),
            DiffChange(
                before_filepath="codecov-alpine",
                after_filepath="codecov-alpine",
                change_type=DiffChangeType.binary,
                lines_only_on_base=None,
                lines_only_on_head=None,
            ),
            DiffChange(
                before_filepath="codecov/settings_dev.py",
                after_filepath="codecov/settings_dev.py",
                change_type=DiffChangeType.modified,
                lines_only_on_base=[],
                lines_only_on_head=[52],
            ),
            DiffChange(
                before_filepath="production.yml",
                after_filepath=None,
                change_type=DiffChangeType.deleted,
                lines_only_on_base=None,
                lines_only_on_head=None,
            ),
        ]
        res = list(parse_git_diff_json({"diff": input_data}))
        assert res == expected_result
