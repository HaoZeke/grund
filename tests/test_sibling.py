"""GRUND_SIBLING_GUARD stays off unless set, and only moves a one-digit sibling."""

from grund.sibling import enabled, shares_stem, siblings_of


def test_flag_is_off_by_default(monkeypatch):
    monkeypatch.delenv("GRUND_SIBLING_GUARD", raising=False)
    assert enabled() is False


def test_one_digit_is_a_shared_stem():
    assert shares_stem("MAN01400", "MAN01401")
    assert shares_stem("VIN00921", "VIN00911")
    assert shares_stem("UTA06001", "UTA06002")
    assert shares_stem("MAN02007", "MAN00101") is False
    assert shares_stem("SKO02202", "SKO02101") is False
    assert shares_stem("PEN02101", "PEN02101") is False


def test_siblings_are_listed_once():
    ids = ["MAN01400.px", "MAN01401.px", "MAN00101.px", "UTA06002.px"]
    assert siblings_of(ids, "MAN01401") == ["MAN01400"]
