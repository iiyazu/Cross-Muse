"""Report lines for invoices and orders."""

from decimal import Decimal

from ledger.money import format_amount, to_decimal_str

Line = tuple[float, int]


def line_total(price: float, quantity: int) -> str:
    """The formatted total of one line."""
    return format_amount(price * quantity)


def order_summary(lines: list[Line]) -> str:
    """One summary row per line, then the subtotal."""
    rows = [f"{quantity} x {format_amount(price)}" for price, quantity in lines]
    subtotal = sum(price * quantity for price, quantity in lines)
    return "\n".join([*rows, "Subtotal: " + format_amount(subtotal)])


def shipping_label(amount: float) -> str:
    """The shipping row of an invoice."""
    return "Shipping: " + format_amount(amount)


def tax_line(subtotal: float, rate: float) -> str:
    """The tax row of an invoice."""
    return "Tax: " + format_amount(subtotal * rate)


def invoice_total(lines: list[Line]) -> str:
    """The formatted grand total of all invoice lines."""
    subtotal = sum(Decimal(str(price)) * quantity for price, quantity in lines)
    return to_decimal_str(subtotal)


def packing_list_path(order_id: str) -> str:
    """Where the packing list for an order is written."""
    return f"reports/pack-{order_id}.txt"


def fee_total(subtotal: float, rate: float) -> str:
    """The formatted fee for a subtotal and rate."""
    return to_decimal_str(Decimal(str(subtotal)) * Decimal(str(rate)))
