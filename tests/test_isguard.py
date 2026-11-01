"""The measure guard is off unless GRUND_IS_KANG_GUARD is set."""

from __future__ import annotations

from grund.isguard import asks_regional_gdp, counted_denies, enabled, guard_reason


def _stated(table: str):
    return {"refused": False, "value": "1", "table_id": table + ".px", "answer": "1"}


def test_flag_is_off_by_default(monkeypatch):
    monkeypatch.delenv("GRUND_IS_KANG_GUARD", raising=False)
    assert enabled() is False
    stated = _stated("MAN00101")
    assert guard_reason("How many deaths were there in Iceland in 2023?", stated) is None


def test_counted_nouns_are_the_deny_list():
    assert counted_denies("How many deaths were there in Iceland in 2023?") == {"deaths"}
    assert counted_denies("Hve margir dóu á Íslandi árið 2024?") == {"deaths"}
    assert counted_denies("Hve margir létust á Íslandi árið 2023?") == {"deaths"}
    assert counted_denies("Hve margir dánir voru á Íslandi árið 2022?") == {"deaths"}
    assert counted_denies("How many marriages were there in Iceland in 2020?") == {"marriages"}
    assert counted_denies("Hve margar hjónavígslur voru árið 2019?") == {"marriages"}
    assert counted_denies("How many hotel beds were there in Iceland in January 2026?") == {"beds"}
    assert counted_denies("Hve mörg rúm voru á hótelum á landinu í júlí 2025?") == {"beds"}
    assert counted_denies("Hve mörg gistirými voru á hótelum árið 2024?") == {"beds"}
    assert counted_denies("Hve margir brottfluttir voru frá Íslandi árið 2024?") == {"emigrants"}
    assert counted_denies("How many Icelandic emigrants were living abroad on 1 January 2026?") == {"emigrants"}


def test_a_population_question_is_not_on_the_deny_list():
    assert counted_denies("How many people lived in Iceland on 1 January 2026?") == set()
    assert counted_denies("Hve margir bjuggu á Íslandi 1. janúar 2026?") == set()
    assert counted_denies("residents of iceland in 2025, how many") == set()
    assert counted_denies("Hve margir Danir bjuggu á Íslandi árið 2024?") == set()
    assert counted_denies("Hver var dánir og dánartíðni, Fjöldi árið 2025?") == set()
    assert counted_denies("What was Marriages dissolved and judicial separations in 2020?") == set()
    assert counted_denies("Hver var munurinn, aðfluttir umfram brottflutta, árið 2023?") == set()


def test_population_table_is_refused_for_another_measure(monkeypatch):
    monkeypatch.setenv("GRUND_IS_KANG_GUARD", "1")
    stated = _stated("MAN00101")
    assert guard_reason("How many deaths were there in Iceland in 2023?", stated)
    assert guard_reason("Hve margar hjónavígslur voru árið 2019?", stated)
    assert guard_reason("How many hotel beds were there in Iceland in January 2026?", stated)
    assert guard_reason("How many Icelandic emigrants were living abroad on 1 January 2026?", stated)
    assert guard_reason("How many people lived in Iceland on 1 January 2026?", stated) is None


def test_the_same_measure_may_be_stated(monkeypatch):
    monkeypatch.setenv("GRUND_IS_KANG_GUARD", "1")
    assert guard_reason("How many deaths were there in Iceland in 2023?", _stated("MAN05210")) is None
    assert guard_reason("How many marriages were there in Iceland in 2020?", _stated("MAN06100")) is None
    assert guard_reason("How many hotel beds were there in Iceland?", _stated("SAM01202")) is None
    assert guard_reason("Hve margir brottfluttir voru frá Íslandi árið 2024?", _stated("MAN01400")) is None


def test_regional_gdp_is_not_the_national_total(monkeypatch):
    monkeypatch.setenv("GRUND_IS_KANG_GUARD", "1")
    assert asks_regional_gdp("Hver var verg landsframleiðsla höfuðborgarsvæðisins árið 2023?")
    assert asks_regional_gdp("What was the GDP of the capital region in 2023?")
    assert asks_regional_gdp("Verg landsframleiðsla árið 2020") is False
    assert guard_reason("What was the GDP of the capital region in 2023?", _stated("THJ01102"))
    assert guard_reason("Verg landsframleiðsla árið 2020", _stated("THJ01102")) is None
    assert guard_reason("How many people lived in the South on 1 January 2026?", _stated("MAN03250")) is None
