from enum import Enum, auto

from services.comparison.overlays.critical_path import CriticalPathOverlay


class OverlayType(Enum):
    line_execution_count = auto()


def get_overlay(overlay_type: OverlayType, comparison, **kwargs) -> CriticalPathOverlay:
    """
    @param comparison: ComparisonProxy (not imported due to circular imports)
    """
    if overlay_type == OverlayType.line_execution_count:
        return CriticalPathOverlay.init_from_comparison(comparison, **kwargs)
