from decimal import Decimal

import pytest

from grund.arithmetic import (
    ArithmeticError,
    per_capita,
    rebase,
    scale_by_unit,
    share_percent,
    yoy_percent,
    format_stat,
)


def test_yoy_percent_uses_decimal_strings():
    assert yoy_percent("656.5", "630.3") == (Decimal("656.5") - Decimal("630.3")) / Decimal("630.3") * 100


def test_yoy_percent_rejects_zero_base():
    with pytest.raises(ArithmeticError):
        yoy_percent("10", "0")


def test_share_and_rebase_and_per_capita():
    assert share_percent("25", "100") == Decimal("25")
    assert rebase("120", "80") == Decimal("150")
    assert per_capita("1000", "250") == Decimal("4")


def test_share_rejects_a_part_larger_than_the_whole():
    with pytest.raises(ArithmeticError):
        share_percent("10.1", "9.3")


def test_scale_only_when_the_unit_is_explicit():
    assert scale_by_unit("3.5", "Thousands") == Decimal("3500")
    assert scale_by_unit("3.5", "Index") == Decimal("3.5")
    assert scale_by_unit("2", "þúsund") == Decimal("2000")


def test_format_stat_groups_thousands_and_keeps_decimals():
    assert format_stat("630.3", "en") == "630.3"
    assert format_stat("630.3", "is") == "630,3"
    assert format_stat("389444", "en") == "389,444"
    assert format_stat("389444", "is") == "389.444"
