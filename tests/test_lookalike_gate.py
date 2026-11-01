"""Look-alike gates withhold a different series and keep the one that matches."""

from grund.lookalike_gate import lookalike_reason


class _Var:
    def __init__(self, text, labels, time=False):
        self.text = text
        self.time = time
        self.values = [(str(index), label) for index, label in enumerate(labels)]


class _Edition:
    def __init__(self, title, path, variables, years):
        self.title = title
        self.db = path[0] if path else ""
        self.path_texts = list(path)
        self.variables = variables
        self._years = set(years)

    def years(self):
        return set(self._years)


class _Table:
    def __init__(self, edition):
        self.editions = {"is": edition, "en": edition}

    def edition(self, _lang):
        return self.editions["is"]


class _Catalogue:
    def __init__(self, mapping):
        self.by_id = mapping


def test_a_historical_copy_is_withheld():
    edition = _Edition(
        "Leiksvið, sætaframboð, uppfærslur, sýningar og gestir leikhúsa 1930-2020",
        ["Sogulegar", "Menning og miðlun"],
        [_Var("Leikár", ["2019/2020"], time=True)],
        [],
    )
    catalogue = _Catalogue({"SOG15009.px": _Table(edition), "MAN02005.px": _Table(_Edition("x", ["Ibuar"], [_Var("Sveitarfélag", ["Reykjavíkurborg"])], []))})
    result = {"value": 4330, "tables": ["SOG15009.px"], "operation": "level"}
    question = "Hver var leiksvið, sætaframboð, uppfærslur, sýningar og gestir leikhúsa tímabilið 2019–2020?"
    assert lookalike_reason(catalogue, question, "is", result) == "historical-copy"


def test_a_named_municipality_on_a_locality_table_is_withheld():
    muni = _Edition(
        "Mannfjöldi eftir kyni, aldri og sveitarfélögum",
        ["Ibuar", "Mannfjöldi"],
        [_Var("Sveitarfélag", ["Akraneskaupstaður", "Reykjavíkurborg"])],
        [2026],
    )
    locality = _Edition(
        "Mannfjöldi eftir þéttbýlisstöðum, kyni og aldri",
        ["Ibuar", "Byggðakjarnar"],
        [_Var("Þéttbýlisstaðir", ["Akranes og nágr."])],
        [2026],
    )
    catalogue = _Catalogue({"MAN02005.px": _Table(muni), "MAN030102.px": _Table(locality)})
    result = {"value": 8607, "tables": ["MAN030102.px"], "operation": "level"}
    assert lookalike_reason(catalogue, "Hvað bjuggu margir á Akranesi 1. janúar 2026?", "is", result) == "wider-geo"


def test_the_municipality_table_itself_is_kept(monkeypatch):
    import grund.lookalike_gate as gate

    monkeypatch.setattr(gate, "search_leader_title", lambda *args: "")
    edition = _Edition(
        "Mannfjöldi eftir kyni, aldri og sveitarfélögum",
        ["Ibuar", "Sveitarfélög"],
        [_Var("Sveitarfélag", ["Akraneskaupstaður"])],
        [2026],
    )
    catalogue = _Catalogue({"MAN02005.px": _Table(edition)})
    result = {"value": 8000, "tables": ["MAN02005.px"], "operation": "level", "answer": "Talan var 8.000."}
    assert lookalike_reason(catalogue, "Hvað bjuggu margir á Akranesi 1. janúar 2026?", "is", result) is None


def test_points_and_a_population_share_are_not_lookalikes(monkeypatch):
    import grund.lookalike_gate as gate

    monkeypatch.setattr(gate, "search_leader_title", lambda *args: "")
    cpi = _Edition(
        "Consumer price index and changes, base 1988=100",
        ["Efnahagur", "Prices"],
        [_Var("Month", ["2025M09", "2026M09"], time=True)],
        list(range(1988, 2027)),
    )
    population = _Edition(
        "Population by regions, sex and age 1 January 1998-2026",
        ["Ibuar", "Population"],
        [_Var("Sex", ["Total", "Females"])],
        [2026],
    )
    catalogue = _Catalogue({"VIS01000.px": _Table(cpi), "MAN03250.px": _Table(population), "MAN02005.px": _Table(population)})
    points = {
        "value": 39.0,
        "operation": "difference",
        "tables": ["VIS01000.px"],
        "claims": [{"cells": [{"title": cpi.title, "labels": {"Index": "Consumer price index"}}]}],
    }
    assert lookalike_reason(
        catalogue,
        "By how many points did the consumer price index rise from September 2025 to September 2026?",
        "en",
        points,
    ) is None
    women = {
        "value": 48.7,
        "operation": "share",
        "tables": ["MAN03250.px"],
        "claims": [{"cells": [{"title": population.title, "labels": {"Sex": "Females"}}]}],
    }
    assert lookalike_reason(
        catalogue,
        "What percentage of Iceland's population on 1 January 2026 were women?",
        "en",
        women,
    ) is None


def test_a_closed_historical_span_is_kept(monkeypatch):
    import grund.lookalike_gate as gate

    monkeypatch.setattr(gate, "search_leader_title", lambda *args: "")
    edition = _Edition(
        "Farþegar og ökutæki með bílferjum til landsins 1981-2017",
        ["Sogulegar", "Ferðaþjónusta"],
        [_Var("Ár", ["2017"], time=True)],
        [],
    )
    catalogue = _Catalogue({"SOG03001.px": _Table(edition), "MAN02005.px": _Table(_Edition("x", ["Ibuar"], [_Var("Sveitarfélag", ["Reykjavíkurborg"])], []))})
    result = {
        "value": 23861,
        "tables": ["SOG03001.px"],
        "operation": "level",
        "source": {"closed_historical": True},
    }
    question = "Hve margir farþegar alls komu með bílferjum til landsins árið 2017?"
    assert lookalike_reason(catalogue, question, "is", result) is None
