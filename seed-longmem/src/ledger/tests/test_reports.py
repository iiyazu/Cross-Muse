from ledger.reports import (
    invoice_total,
    line_total,
    order_summary,
    packing_list_path,
    shipping_label,
    tax_line,
)


def test_line_total() -> None:
    assert line_total(2.5, 4) == "10.00"


def test_order_summary() -> None:
    assert order_summary([(1.0, 2), (3.5, 1)]).endswith("Subtotal: 5.50")


def test_shipping_and_tax() -> None:
    assert shipping_label(4.0) == "Shipping: 4.00"
    assert tax_line(10.0, 0.2) == "Tax: 2.00"


def test_invoice_total() -> None:
    assert invoice_total([(2.675, 1)]) == "2.68"


def test_packing_list_path() -> None:
    assert packing_list_path("001") == "reports/pack-001.txt"
