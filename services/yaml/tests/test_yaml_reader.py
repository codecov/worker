from decimal import Decimal

from shared.yaml.user_yaml import UserYaml

from helpers.components import Component
from services.yaml.reader import (
    get_components_from_yaml,
    get_paths_from_flags,
    round_number,
)


class TestYamlReader(object):
    def test_round_number(self):
        round_up_yaml_dict = {"coverage": {"precision": 5, "round": "up"}}
        assert Decimal("1.23457") == round_number(
            round_up_yaml_dict, Decimal("1.23456789")
        )
        assert Decimal("1.23457") == round_number(
            round_up_yaml_dict, Decimal("1.234565")
        )
        assert Decimal("1.23456") == round_number(
            round_up_yaml_dict, Decimal("1.234555")
        )
        round_down_yaml_dict = {"coverage": {"precision": 5, "round": "down"}}
        assert Decimal("1.23456") == round_number(
            round_down_yaml_dict, Decimal("1.23456789")
        )
        assert Decimal("1.23456") == round_number(
            round_down_yaml_dict, Decimal("1.234565")
        )
        assert Decimal("1.23455") == round_number(
            round_down_yaml_dict, Decimal("1.234555")
        )
        yaml_dict = {"coverage": {"precision": 5, "round": "nearest"}}
        assert Decimal("1.23457") == round_number(yaml_dict, Decimal("1.23456789"))
        assert Decimal("1.23456") == round_number(yaml_dict, Decimal("1.234565"))
        assert Decimal("1.23456") == round_number(yaml_dict, Decimal("1.234555"))

    def test_get_paths_from_flags(self):
        yaml_dict = UserYaml(
            {
                "flags": {
                    "sample_1": {"paths": ["path_1/.*", r"path_2/.*\.py"]},
                    "sample_2": {"paths": None},
                    "sample_3": {"paths": ["path_1/.*"]},
                    "sample_4": {"paths": []},
                    "sample_5": {
                        "paths": [
                            "path_5/.*",
                            r"path_6/.*/[^\/]+",
                            r"path_8/specific\.py",
                        ]
                    },
                }
            }
        )
        flags_to_use = ["sample_1", "sample_4", "sample_5"]
        expected_result = [
            "path_1/.*",
            r"path_2/.*\.py",
            "path_5/.*",
            r"path_6/.*/[^\/]+",
            r"path_8/specific\.py",
        ]
        result = get_paths_from_flags(yaml_dict, flags_to_use)
        assert set(expected_result) == set(result)
        assert [] == get_paths_from_flags(
            yaml_dict, ["sample_1", "sample_2", "sample_4", "sample_5"]
        )
        assert [
            "path_1/.*",
            r"path_2/.*\.py",
            "path_5/.*",
            r"path_6/.*/[^\/]+",
            r"path_8/specific\.py",
        ] == sorted(
            get_paths_from_flags(
                yaml_dict, ["sample_1", "sample_4", "sample_5", "banana"]
            )
        )

    def test_get_components_no_default(self):
        yaml_dict = UserYaml(
            {
                "component_management": {
                    "individual_components": [
                        {"component_id": "py_files", "paths": [r".*\.py"]}
                    ]
                }
            }
        )
        components = get_components_from_yaml(yaml_dict)
        assert len(components) == 1
        assert components == [
            Component(
                component_id="py_files",
                paths=[r".*\.py"],
                name="",
                flag_regexes=[],
                statuses=[],
            )
        ]

    def test_get_components_default_no_components(self):
        yaml_dict = UserYaml({"component_management": {}})
        components = get_components_from_yaml(yaml_dict)
        assert len(components) == 0

    def test_get_components_default_only(self):
        yaml_dict = UserYaml(
            {
                "component_management": {
                    "default_rules": {"paths": [r".*\.py"], "flag_regexes": [r"flag.*"]}
                }
            }
        )
        components = get_components_from_yaml(yaml_dict)
        assert len(components) == 0

    def test_get_components_all(self):
        yaml_dict = UserYaml(
            {
                "component_management": {
                    "default_rules": {
                        "paths": [r".*\.py"],
                        "flag_regexes": [r"flag.*"],
                    },
                    "individual_components": [
                        {"component_id": "go_files", "paths": [r".*\.go"]},
                        {"component_id": "rules_from_default"},
                        {
                            "component_id": "I have my flags",
                            "flag_regexes": [r"python-.*"],
                        },
                        {
                            "component_id": "required",
                            "name": "display",
                            "flag_regexes": [],
                            "paths": [r"src/.*"],
                        },
                    ],
                }
            }
        )
        components = get_components_from_yaml(yaml_dict)
        assert len(components) == 4
        assert components == [
            Component(
                component_id="go_files",
                paths=[r".*\.go"],
                name="",
                flag_regexes=[r"flag.*"],
                statuses=[],
            ),
            Component(
                component_id="rules_from_default",
                paths=[r".*\.py"],
                name="",
                flag_regexes=[r"flag.*"],
                statuses=[],
            ),
            Component(
                component_id="I have my flags",
                paths=[r".*\.py"],
                name="",
                flag_regexes=[r"python-.*"],
                statuses=[],
            ),
            Component(
                component_id="required",
                name="display",
                paths=[r"src/.*"],
                flag_regexes=[],
                statuses=[],
            ),
        ]
