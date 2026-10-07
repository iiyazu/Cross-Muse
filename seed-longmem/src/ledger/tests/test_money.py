from decimal import Decimal

import pytest

from ledger.money import to_decimal_str


def test_round_half_up() -> None:
    assert to_decimal_str(Decimal("2.675")) == "2.68"


def test_rejects_float() -> None:
    with pytest.raises(TypeError):
        to_decimal_str(2.675)  # type: ignore[arg-type]
