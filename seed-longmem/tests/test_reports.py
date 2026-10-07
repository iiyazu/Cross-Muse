from src.ledger.reports import line_total, order_summary


def test_line_total() -> None:
    assert line_total(2.5, 4) == "10.00"


def test_order_summary() -> None:
    assert order_summary([(1.0, 2), (3.5, 1)]).endswith("Subtotal: 5.50")
