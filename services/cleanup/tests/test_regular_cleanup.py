import pytest

from services.cleanup.regular import run_regular_cleanup
from services.cleanup.utils import CleanupResult, CleanupSummary


@pytest.mark.django_db
def test_runs_regular_cleanup():
    summary = run_regular_cleanup()

    assert summary == CleanupSummary(CleanupResult(0, 0), {})
