import pytest

from grund_eval.metrics import summarise, wilson


def test_wilson_known_ends():
    assert wilson(0, 0) is None
    low, high = wilson(0, 10)
    assert low == 0
    assert 0.25 < high < 0.35
    low, high = wilson(100, 100)
    assert high == 1
    assert low > 0.95


def test_wilson_rejects_impossible_counts():
    with pytest.raises(ValueError):
        wilson(5, 3)


def test_summarise_skips_rows_that_do_not_apply():
    rows = [
        {"value_correct": True},
        {"value_correct": False},
        {"value_correct": None},
    ]
    summary = summarise(rows, "value_correct")
    assert summary["n"] == 2
    assert summary["successes"] == 1
    assert summary["accuracy"] == 0.5
