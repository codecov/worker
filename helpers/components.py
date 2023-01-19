import re
from dataclasses import dataclass
from typing import List


@dataclass
class Component:
    """
    Virtual representation of components defined in the user_schema yaml.
    Definition: https://github.com/codecov/shared/pull/312/commits/c7bd48173da914bb16137526015791cb5a3c931c
    """

    component_id: str
    name: str
    flag_regexes: List[str]
    paths: List[str]
    statuses: List[dict]

    @classmethod
    def from_dict(cls, component_dict):
        return Component(
            component_id=component_dict.get("component_id", ""),
            name=component_dict.get("name", ""),
            flag_regexes=component_dict.get("flag_regexes", []),
            paths=component_dict.get("paths", []),
            statuses=component_dict.get("statuses", []),
        )

    def get_display_name(self) -> str:
        return self.name or self.component_id or "default_component"

    def get_matching_flags(self, current_flags: List[str]) -> List[str]:
        ans = set()
        compiled_regexes = map(
            lambda flag_regex: re.compile(flag_regex), self.flag_regexes
        )
        for regex_to_match in compiled_regexes:
            matches_to_this_regex = filter(
                lambda flag: regex_to_match.match(flag), current_flags
            )
            ans.update(matches_to_this_regex)
        return list(ans)
