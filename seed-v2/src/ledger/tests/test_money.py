from decimal import Decimal

from ledger.money import to_decimal_str


def test_round_half_up() -> None:
    assert to_decimal_str(Decimal("2.675")) == "2.68"
