from shared.reports.types import ReportTotals


def minimal_totals(totals: ReportTotals | None) -> dict:
    if totals is None:
        return {
            "hits": 0,
            "misses": 0,
            "partials": 0,
            "coverage": None,
        }
    return {
        "hits": totals.hits,
        "misses": totals.misses,
        "partials": totals.partials,
        # ReportTotals has coverage as a string, we want float in the DB
        # Also the coverage from ReportTotals is 0-100, while in the DB it's 0-1
        "coverage": (
            (float(totals.coverage) / 100) if totals.coverage is not None else None
        ),
    }
