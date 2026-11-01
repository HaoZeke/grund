from grund.headline import is_breakdown
from grund_index.catalogue import Hit
from grund_index.model import Edition, Table


def _hit(title, path):
    edition = Edition("en", title, "Ibuar", [], path, "http://example", None, [])
    return Hit(Table(title, {"en": edition}), 1.0, 0.0, 0.0, 0.0)


def test_a_bare_population_question_skips_country_of_birth():
    birth = _hit("Population by country of birth, sex and age", ["Population"])
    stock = _hit("Population - key figures", ["Population", "Overview"])
    assert is_breakdown(birth, "How many people lived in Iceland on 1 January 2026?")
    assert not is_breakdown(stock, "How many people lived in Iceland on 1 January 2026?")


def test_an_unqualified_cpi_question_treats_the_ex_housing_index_as_a_breakdown():
    housing = _hit("Vísitala neysluverðs án húsnæðis, júlí 1914=100", ["Prices"])
    headline = _hit("Vísitala neysluverðs og breytingar, grunnur 1988=100", ["Prices"])
    asked = "Hvar stóð vísitala neysluverðs í desember 2023?"
    assert is_breakdown(housing, asked)
    assert not is_breakdown(headline, asked)


def test_hotels_are_not_the_headline_for_all_accommodation():
    hotels = _hit("Gistinætur og gestakomur á hótelum", ["Tourism"])
    whole = _hit("Gistinætur og gestakomur á öllum tegundum skráðra gististaða", ["Tourism"])
    asked = "Hve margar gistinætur voru skráðar árið 2023?"
    assert is_breakdown(hotels, asked)
    assert not is_breakdown(whole, asked)


def test_a_named_town_keeps_the_municipality_table():
    city = _hit("Population in Reykjavik by districts", ["Population", "Municipalities"])
    assert not is_breakdown(city, "Hve margir bua i Reykjavik?")
