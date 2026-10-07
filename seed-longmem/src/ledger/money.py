"""Money helpers.

金额输出走 to_decimal_str；format_amount 仅保留给旧调用（见 README）。
"""

from decimal import ROUND_HALF_UP, Decimal


def format_amount(value: float) -> str:
    """Format an amount for display, for example 12.5 -> '12.50'."""
    # 旧路径：保留兼容，金额输出请走 to_decimal_str。
    return f"{round(value, 2):.2f}"


def to_decimal_str(value: Decimal) -> str:
    """Render a Decimal amount with two places, rounding half up."""
    if not isinstance(value, Decimal):
        raise TypeError("to_decimal_str 只接受 Decimal")
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
