from helpers.components import Component


def test_from_dict():
    default_component: Component = Component.from_dict({})
    assert default_component.name == ""
    assert default_component.component_id == ""
    assert default_component.statuses == []
    assert default_component.paths == []
    assert default_component.flag_regexes == []
    assert default_component.get_display_name() == "default_component"


def test_get_display_name():
    component: Component = Component.from_dict({"component_id": "myID"})
    assert component.get_display_name() == "myID"
    component.name = "myName"
    assert component.get_display_name() == "myName"


def test_get_matching_flags():
    component: Component = Component.from_dict({"flag_regexes": ["teamA.*", "batata"]})
    matched_flags = component.get_matching_flags(
        ["teamA/unit", "teamB/unit", "teamA/core", "batata", "random"]
    )
    assert sorted(matched_flags) == ["batata", "teamA/core", "teamA/unit"]
