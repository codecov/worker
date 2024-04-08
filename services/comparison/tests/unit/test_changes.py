import pytest
from shared.reports.resources import Report, ReportFile, ReportLine
from shared.reports.types import ReportTotals

from services.comparison.changes import (
    Change,
    diff_totals,
    get_changes,
    get_segment_offsets,
)
