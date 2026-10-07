"""Report lines for invoices and orders."""

from src.ledger.money import format_amount

Line = tuple[float, int]


def line_total(price: float, quantity: int) -> str:
    """The formatted total of one line."""
    return format_amount(price * quantity)


def order_summary(lines: list[Line]) -> str:
    """One summary row per line, then the subtotal."""
    rows = [f"{quantity} x {format_amount(price)}" for price, quantity in lines]
    subtotal = sum(price * quantity for price, quantity in lines)
    return "\n".join([*rows, "Subtotal: " + format_amount(subtotal)])
