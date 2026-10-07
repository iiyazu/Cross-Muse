"""Money helpers."""


def format_amount(value: float) -> str:
    """Format an amount for display, for example 12.5 -> '12.50'."""
    return f"{round(value, 2):.2f}"
