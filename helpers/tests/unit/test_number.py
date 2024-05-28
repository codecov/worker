from decimal import Decimal

import pytest

from helpers.number import precise_round


@pytest.mark.parametrize(
    "number,precision,rounding,expected_rounding",
    [
        (Decimal("1.129"), 2, "down", Decimal("1.12")),
        (Decimal("1.121"), 2, "up", Decimal("1.13")),
        (Decimal("1.125"), 1, "nearest", Decimal("1.1")),
        (Decimal("1.18"), 1, "nearest", Decimal("1.2")),
        (Decimal("1.15"), 1, "nearest", Decimal("1.2")),
        (Decimal("1.25"), 1, "nearest", Decimal("1.2")),
    ],
    ids=[
        "number rounds down",
        "number rounds up",
        "number rounds nearest (down)",
        "number rounds nearest (up)",
        "number rounds half-even (up)",
        "number rounds half-even (down)",
    ],
)
def test_precise_round(
    number: Decimal, precision: int, rounding: str, expected_rounding: Decimal
):
    assert expected_rounding == precise_round(
        number, precision=precision, rounding=rounding
    )
