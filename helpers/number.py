from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal


def precise_round(
    number: Decimal, precision: int = 2, rounding: str = "down"
) -> Decimal:
    """
    Helper function to do more precise rounding given a precision and rounding strategy.
    :param number: Number to round
    :param precision: The number of decimal places to round to
    :param rounding: Rounding strategy to use, which can be "down", "up" or "nearest"
    :return: The rounded number as a Decimal object
    """
    quantizer = Decimal("0.1") ** precision
    if rounding == "up":
        return number.quantize(quantizer, rounding=ROUND_CEILING)
    if rounding == "down":
        return number.quantize(quantizer, rounding=ROUND_FLOOR)
    return number.quantize(quantizer, rounding=ROUND_HALF_EVEN)
