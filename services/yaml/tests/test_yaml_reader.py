from decimal import Decimal

from shared.yaml.user_yaml import UserYaml

from services.yaml.reader import get_paths_from_flags, round_number


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
        flags_to_use = ["sample_1", "sample_2", "sample_4", "sample_5"]
        expected_result = [
            "path_1/.*",
            r"path_2/.*\.py",
            "path_5/.*",
            r"path_6/.*/[^\/]+",
            r"path_8/specific\.py",
        ]
        result = get_paths_from_flags(yaml_dict, flags_to_use)
        assert set(expected_result) == set(result)
