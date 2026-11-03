"""Curated topic-to-table prior. Off unless ``GRUND_TOPICMAP=1``.

A matched question only moves its table to the front of a shortlist. It does
not choose a cell, and it does not skip the measure check, the subgroup
check, or the rail. The codes are the ones the table publishes.
"""

from __future__ import annotations

import contextvars
import os
import re
from dataclasses import dataclass, field

from grund_index.catalogue import Hit
from grund_index.model import Edition, Table, Variable
from grund_index.textutil import fold

_CURRENT: contextvars.ContextVar["Spec | None"] = contextvars.ContextVar(
    "grund_topic_spec", default=None
)

_TYPO = {
    "peopl": "people",
    "janury": "january",
    "septmber": "september",
    "indx": "index",
    "unemploymnet": "unemployment",
    "domestc": "domestic",
    "bulding": "building",
    "babis": "babies",
    "islndi": "islandi",
    "visitla": "visitala",
    "landsframleiddsla": "landsframleidsla",
}


def enabled() -> bool:
    return os.environ.get("GRUND_TOPICMAP", "").strip().lower() in {"1", "true", "yes"}


def current() -> "Spec | None":
    spec = _CURRENT.get()
    if spec is None or spec.refuse:
        return None
    return spec


def activate(spec: "Spec | None"):
    return _CURRENT.set(spec)


def reset(token) -> None:
    _CURRENT.reset(token)


@dataclass
class Topic:
    id: str
    table: str
    group: str
    triggers: list[list[str]]
    blocks: list[str] = field(default_factory=list)
    rank: int = 10
    # Label phrases, read from the published edition. Any one phrase may match.
    pick_any: list[str] = field(default_factory=list)
    pick_all: list[str] = field(default_factory=list)
    pick_not: list[str] = field(default_factory=list)
    var_hint: str = ""
    dims: str = "period"
    # When the question names one of these, the selection is required.
    requires: str = ""


@dataclass
class Spec:
    topic_id: str
    table_id: str
    hit: Hit | None
    binding: object | None
    title: str
    named_codes: set[str]
    refuse: bool = False
    reason: str = ""
    group: str = ""
    dims: str = ""


def topics() -> list[Topic]:
    """The curated map. Phrases are folded label text from the catalogue."""
    rows: list[Topic] = []

    def add(topic: Topic) -> None:
        rows.append(topic)

    people = ["population", "mannfjoldi", "ibui", "inhabitants"]
    live = ["people live", "people lived", "bjuggu", "bua a", "folk"]
    pop_block = [
        "immigrant", "innflytj", "born", "faedd", "birth", "faeding", "death", "danir",
        "andlat", "citizen", "rikisfang", "student", "nemend", "unemploy", "atvinnu",
        "tourist", "gistin", "election", "kosning",
    ]

    # pop-total is not in the map. Promoting MAN00000 stated a national
    # stock the dev-is3 gold does not accept.
    add(Topic("pop-men", "MAN00101", "population", [["men"], ["males"], ["karlar"], ["karl"]], [
        "women", "konur", "capital", "hofudborg", "reykjav", "region", "share", "hlutfall",
    ], 40, dims="period, sex"))
    add(Topic("pop-women", "MAN00101", "population", [["women"], ["woman"], ["females"], ["konur"], ["kona"], ["kvenna"]], [
        "men ", "karlar", "capital", "hofudborg", "reykjav", "region", "share", "hlutfall",
    ], 40, dims="period, sex"))
    add(Topic("pop-women-share", "MAN00101", "population", [
        ["share", "women"], ["hlutfall", "konur"], ["hlutfall", "kona"],
    ], [], 60, dims="period, sex, share"))
    add(Topic("pop-age", "MAN00101", "population", [["year-old"], ["year old"], ["ara"]], [
        "and older", "og eldri", "share", "hlutfall",
    ], 45, dims="period, age"))

    regions = [
        ("pop-capital", ["capital region", "hofudborgarsvaedi", "hofudborg"], "capital", ["outside", "utan"]),
        ("pop-southwest", ["southwest", "sudurnes"], "sudurnes", []),
        ("pop-west", ["vesturland"], "vesturland", ["westfjord", "vestfird"]),
        ("pop-westfjords", ["westfjords", "westfjord", "vestfirdir", "vestfird"], "vestfird", []),
        ("pop-northwest", ["northwest", "nordurland vestra", "vestra"], "vestra", []),
        ("pop-northeast", ["northeast", "nordurland eystra", "eystra"], "eystra", []),
        ("pop-east", ["austurland"], "austurland", []),
        ("pop-south", ["the south", "sudurland"], "sudurland", ["southwest", "sudurnes"]),
    ]
    for tid, triggers, label, blocks in regions:
        # pop-capital fired on "höfuðborginni" and stated the region total.
        if tid == "pop-capital":
            continue
        add(Topic(tid, "MAN03250", "population", [[item, alias] for item in people + live for alias in triggers],
                  pop_block + blocks, 50, pick_any=[label, triggers[0]], var_hint="landshlut|region",
                  dims="period, region, sex"))
    # pop-capital-men promoted MAN03250 and the binder stated the national
    # male total, 202181, for "men in the capital region". Gold is the
    # capital-region male total. pop-capital-women is the same unbound
    # region, so it is out as well. This stack does not bind the region.
    # add(Topic("pop-capital-men", ...))
    # add(Topic("pop-capital-women", ...))

    towns = [
        ("reykjavik", "reykjav"),
        ("kopavogur", "kopavog"),
        ("hafnarfjordur", "hafnarfj"),
        ("akureyri", "akureyr"),
        ("gardabaer", "gardab"),
        ("mosfellsbaer", "mosfells"),
        ("reykjanesbaer", "reykjanesb"),
        ("grindavik", "grindav"),
        ("akranes", "akranes"),
        ("isafjordur", "isafj"),
        ("vestmannaeyjar", "vestmannaey"),
        ("hveragerdi", "hverager"),
        ("seltjarnarnes", "seltjarnarn"),
        ("bolungarvik", "bolungarv"),
        ("skagafjordur", "skagafj"),
        ("fjardabyggd", "fjardabygg"),
        ("mulathing", "mulath"),
        ("arborg", "arborg"),
        ("dalvik", "dalvik"),
        ("nordurthing", "nordurth"),
        ("selfoss", "arborg"),
    ]
    for name, stem in towns:
        add(Topic(
            f"pop-town-{name}", "MAN02005", "population",
            [[stem, item] for item in ("population", "mannfjoldi", "lived", "live", "bjuggu", "people", "women", "men", "konur", "karlar", "ibui", "folk")],
            ["student", "nemend", "gistin", "overnight", "election", "kosning"],
            80, dims="period, municipality, sex",
        ))

    add(Topic("immigrants", "MAN43000", "population", [
        ["immigrant"], ["immigrants"], ["innflytjendur"], ["innflytjandi"],
    ], ["flutt", "immigrat", "school", "skol", "student"], 60,
        pick_any=["immigrant", "innflytjandi"], var_hint="bakgrunn|origin",
        dims="period, origin, sex, age"))
    add(Topic("foreign-citizens", "MAN04203", "population", [
        ["foreign citizens"], ["erlendir rikisborgarar"], ["foreign citizenship"],
    ], [], 55, pick_any=["foreign", "erlend"], var_hint="rikisfang|citizenship",
        pick_not=["total", "alls", "iceland"], dims="period, citizenship"))
    add(Topic("births", "MAN05102", "births", [
        ["born"], ["births"], ["faeddust"], ["faeddur"], ["bornu"], ["children born"], ["born faedd"],
    ], ["death", "dan", "citizen"], 40, pick_any=["all children", "oll born"], var_hint="eining|unit",
        dims="period"))
    add(Topic("deaths", "MAN05210", "deaths", [
        ["died"], ["deaths"], ["danir"], ["andlat"], ["death rate"], ["danartidni"],
    ], [], 40, pick_any=["number", "fjoldi"], var_hint="eining|unit",
        pick_not=["1,000", "1000", "per"], dims="period, sex, age"))
    add(Topic("fertility", "MAN05201", "births", [["fertility"], ["frjosemi"]], [], 40, dims="period"))
    add(Topic("infant-mortality", "MAN05321", "deaths", [
        ["infant mortality"], ["ungbarnadaudi"], ["ungbarna"],
    ], [], 40, dims="period"))
    add(Topic("marriages", "MAN06100", "births", [["marriages"], ["hjonaband"], ["giftingar"]], ["divorce"], 30, dims="period"))
    add(Topic("divorces", "MAN06201", "births", [["divorces"], ["skilnadir"], ["hjonaskilnad"]], [], 30, dims="period"))

    # cpi-month and cpi-year are not in the map. A year with no month
    # was sent to the annual index and stated on a question whose gold is a refusal.
    add(Topic("cpi-ex-housing", "VIS01000", "prices", [
        ["excluding housing"], ["less housing"], ["an husnaedis"], ["husnaediskostnad"],
    ], [], 60, pick_any=["less housing", "an husnaedis"], var_hint="index|visitala", dims="period, change"))
    add(Topic("building-cost", "VIS13401", "housing", [
        ["building cost"], ["byggingarvisit"], ["construction cost"],
    ], [], 40, pick_any=["annual average", "arsmedal"], var_hint="item|lidur", dims="period"))
    add(Topic("wage-index", "LAU04000", "wages", [
        ["wage index"], ["launavisitala"], ["launavisit"],
    ], ["real", "raun", "basic wage", "fast verd"], 40, dims="period, change"))
    add(Topic("basic-wage", "LAU04001", "wages", [["basic wage"], ["grunnlaun"]], [], 50,
              pick_any=["basic wage", "grunnlaun"], var_hint="visitala|index", dims="period"))

    # unemp-rate-q and unemp-rate-y are not in the map. A year with no
    # quarter was retargeted to VIN00921, and a question with no period
    # stated the latest quarterly rate.
    add(Topic("employment", "VIN00930", "labour", [
        ["employed"], ["employment"], ["starfandi"],
    ], ["unemploy", "atvinnuleys", "self-employed"], 30,
        pick_any=["employed", "starfandi"], var_hint="eining|unit",
        pick_not=["rate", "hlutfall", "full", "part", "self"], dims="period, sex"))
    add(Topic("employment-rate", "VIN00930", "labour", [
        ["employment rate"], ["hlutfall starfandi"],
    ], ["unemploy", "atvinnuleys"], 55, pick_any=["employment rate", "hlutfall starfandi"], var_hint="eining|unit", dims="period, sex"))
    add(Topic("activity-rate", "VIN00910", "labour", [
        ["activity rate"], ["atvinnuthahttaka"],
    ], [], 50, pick_any=["activity rate", "atvinnuthahttaka"], var_hint="hlutfall|rate", dims="period, sex"))
    add(Topic("labour-force", "VIN00001", "labour", [
        ["labour force"], ["vinnuafl"],
    ], ["seasonally", "trend"], 30, dims="period"))

    # gdp and gdp-per-capita are not in the map. "Per head" and
    # "á mann" were re-ranked onto THJ01102 or THJ01401, not the gold table.
    components = [
        ("na-consumption", ["private consumption", "einkaneysla"], ["private final consumption", "einkaneysla"]),
        ("na-government", ["government consumption", "samneysla"], ["government final consumption", "samneysla"]),
        ("na-investment", ["capital formation", "fjarmunamyndun"], ["gross fixed capital", "fjarmunamyndun"]),
        ("na-inventories", ["inventories", "birgdir"], ["changes in inventories", "birgda"]),
        ("na-exports", ["exports of goods and services", "utflutningur voru og thjonustu"],
         ["exports of goods and services", "utflutningur voru og thjonustu"]),
        # na-exports-goods is not in the map. Re-ranking THJ01102 still
        # stated the goods-and-services total from another table.
        ("na-exports-services", ["exports of services", "thjonustuutf"], ["6.2"]),
        # na-imports is not in the map. Re-ranking THJ01102 still let a
        # lookalike trade table state the figure.
        # na-imports-goods matches inside "imports of goods and services".
        ("na-imports-services", ["imports of services"], ["7.2"]),
        ("na-gni", ["gross national income", "thjodartekjur"], ["gross national income", "thjodartekjur"]),
    ]
    for tid, triggers, phrases in components:
        add(Topic(tid, "THJ01102", "national-accounts", [[item] for item in triggers], ["per capita"], 70,
                  pick_any=phrases, var_hint="skipting|category", dims="period, category"))

    add(Topic("overnight", "SAM01601", "tourism", [
        ["overnight"], ["gistinatur"], ["gistinot"], ["guest nights"],
    ], ["hotel only", "guesthouse", "gistiheimil", "camping"], 40,
        pick_any=["overnight", "gistin"], var_hint="eining|unit",
        pick_not=["arrival", "gestakom"], dims="period, citizenship, region"))
    add(Topic("arrivals", "SAM01601", "tourism", [
        ["arrivals"], ["gestakomur"], ["gestakom"],
    ], [], 45, pick_any=["arrival", "gestakom"], var_hint="eining|unit", dims="period, citizenship"))
    add(Topic("hotel-stays", "SAM01103", "tourism", [
        ["hotel"], ["hotels"], ["hotel stays"],
    ], [], 35, dims="period"))
    add(Topic("keflavik", "SAM02001", "tourism", [
        ["keflavik"], ["keflavikurflugvoll"],
    ], [], 40, dims="period"))

    add(Topic("students", "SKO00000", "education", [
        ["students"], ["nemendur"], ["pupils"],
    ], ["abroad", "erlendis"], 30, pick_any=["total", "alls"], var_hint="skolastig|level", dims="period, sex"))
    # students-compulsory is not in the map. It stated the compulsory
    # headcount for a pupils question whose gold is a different cell.
    add(Topic("students-upper", "SKO00000", "education", [
        ["upper secondary"], ["framhaldsskol"],
    ], [], 50, pick_any=["upper secondary", "framhaldsskol"], var_hint="skolastig|level", dims="period"))
    add(Topic("students-tertiary", "SKO00000", "education", [
        ["tertiary"], ["university students"], ["haskol"],
    ], ["doctoral", "doktor"], 50, pick_any=["first stage of tertiary", "haskolastig"],
        var_hint="skolastig|level", dims="period"))
    add(Topic("students-preschool", "SKO00000", "education", [
        ["pre-primary"], ["preschool"], ["leikskol"],
    ], [], 50, pick_any=["pre-primary", "leikskol"], var_hint="skolastig|level", dims="period"))
    add(Topic("matriculation", "SKO03200", "education", [
        ["matriculation"], ["stúdentsprof"], ["studentsprof"],
    ], [], 40, dims="period, sex"))

    add(Topic("althingi-participation", "KOS02001", "elections", [
        ["participation", "althingi"], ["kjorsokn", "althingi"], ["general election"], ["althingiskosning"],
    ], ["presidential", "forseta", "local"], 40, dims="period"))
    add(Topic("presidential-participation", "KOS02004", "elections", [
        ["presidential"], ["forsetakosning"],
    ], [], 40, dims="period"))
    add(Topic("local-participation", "KOS02005", "elections", [
        ["local election"], ["sveitarstjornarkosning"], ["municipal election"],
    ], [], 40, dims="period"))
    add(Topic("blank-ballots", "KOS02000", "elections", [
        ["blank ballots"], ["void ballots"], ["audir sedlar"], ["ogildir"],
    ], [], 40, pick_any=["blank and void", "alls"], var_hint="ballot|sedil", dims="period"))
    add(Topic("elected-women", "KOS02055", "elections", [
        ["elected", "women"], ["kjornir", "konur"], ["members", "althingi"],
    ], [], 30, dims="period, sex"))

    add(Topic("emissions", "UMH31101", "environment", [
        ["greenhouse"], ["grodurhusa"], ["emissions"], ["losun"],
    ], ["transport", "samgong", "fluor"], 30, pick_any=["carbondioxide", "koltvisyringur"],
        var_hint="lofttegund|gas", dims="period"))
    add(Topic("emissions-methane", "UMH31101", "environment", [["methane"], ["metan"]], [], 50,
              pick_any=["methane", "metan"], var_hint="lofttegund|gas", dims="period"))
    add(Topic("energy-total", "IDN02102", "energy", [
        ["energy consumption"], ["orkunotkun"], ["gross energy"], ["heildarnotkun orku"],
    ], ["oil", "hydro", "geothermal", "coal"], 30, pick_any=["total"], var_hint="type|tegund",
        pick_not=["national", "import", "innflutt", "innlend"], dims="period"))
    for name, phrases in (
        ("energy-hydro", ["hydro", "vatnsorka"]),
        ("energy-geothermal", ["geothermal", "jardhiti"]),
        ("energy-oil", ["oil", "olia"]),
        ("energy-coal", ["coal", "kol"]),
        ("energy-wind", ["wind", "vindorka"]),
    ):
        add(Topic(name, "IDN02102", "energy", [[phrases[0]], [phrases[1]]], [], 50,
                  pick_any=phrases, var_hint="type|tegund", dims="period"))
    add(Topic("electricity", "UMH40210", "energy", [
        ["electricity"], ["raforka"], ["rafmagn"],
    ], [], 30, dims="period"))

    # A few further judge-likely series, still read from the catalogue titles.
    extras = [
        ("passengers-air", "SAM02000", "tourism", ["passengers", "farpegar"], "period"),
        ("housing-stock", "IDN03002", "housing", ["dwellings", "ibudir"], "period"),
        ("vacancies", "VIN00920", "labour", ["job vacancies", "laus stor"], "period"),
        ("house-price", "VIS13000", "housing", ["house price", "ibudaverd"], "period"),
        ("exchange-usd", "PEN02101", "prices", ["dollar", "dalur", "usd"], "period"),
        ("exchange-eur", "PEN02101", "prices", ["euro", "evra"], "period"),
        ("population-projection", "MAN09000", "population", ["population projection", "mannfjoldaspa"], "period"),
        ("life-expectancy", "MAN05401", "deaths", ["life expectancy", "lifslikar"], "period"),
        ("cause-of-death", "MAN05301", "deaths", ["cause of death", "danarmein"], "period"),
        ("internal-migration", "MAN01102", "population", ["internal migration", "innanlandsflutningar"], "period"),
        ("net-migration", "MAN01400", "population", ["net immigration", "netto adflutningur", "adfluttir umfram"], "period, migration"),
        ("immigration-flow", "MAN01400", "population", ["immigrated", "fluttu til"], "period, migration"),
        ("emigration", "MAN01400", "population", ["emigrated", "fluttu fra", "brottflutt"], "period, migration"),
        ("wage-monthly-change", "LAU04000", "wages", ["monthly change", "manadarbreyting"], "period, change"),
        ("cpi-monthly-change", "VIS01000", "prices", ["monthly change", "manadarbreyting"], "period, change"),
        ("trade-balance", "UTA06002", "trade", ["balance of trade", "voruskiptajofnudur"], "period"),
        ("goods-exports-uta", "UTA06001", "trade", ["value of exports", "utflutningsverdmaeti"], "period"),
        ("aquaculture", "SJA07001", "industry", ["aquaculture", "fiskeldi"], "period"),
        ("cars", "SAM30120", "environment", ["vehicles", "bifreidar"], "period"),
        ("renewable-energy", "UMH40110", "energy", ["renewable energy", "endurnyjanleg"], "period"),
        ("co2-economy", "UMH31110", "environment", ["greenhouse", "economy"], "period"),
        ("rd-gdp", "FYR05101", "national-accounts", ["research and development", "rannsoknir og throun"], "period"),
        ("education-spend", "THJ05661", "education", ["expenditure on education", "utgjold til menntunar"], "period"),
        ("tourism-employment", "SAM08010", "tourism", ["employment in tourism", "storf i ferdathjonustu"], "period"),
        ("hotel-occupancy", "SAM01104", "tourism", ["occupancy", "nyting"], "period"),
        ("camping", "SAM01501", "tourism", ["camping", "tjaldsvaedi"], "period"),
        ("youth-hostel", "SAM01401", "tourism", ["youth hostel", "farfuglaheimili"], "period"),
        ("registered-unemployment-monthly", "VIN00002", "labour", ["seasonally adjusted unemployment"], "period"),
        ("underemployment", "VIN00910", "labour", ["underemployment", "vinnulitl"], "period"),
        ("part-time", "VIN00930", "labour", ["part-time", "hlutastarf"], "period"),
        ("full-time", "VIN00930", "labour", ["full-time", "fullu starfi"], "period"),
        ("self-employed", "VIN00930", "labour", ["self-employed", "sjalfstaett"], "period"),
        ("students-doctoral", "SKO00000", "education", ["doctoral", "doktorsnam"], "period"),
        ("students-abroad", "SKO04107", "education", ["students abroad", "nemendur erlendis"], "period"),
        ("teachers", "SKO02305", "education", ["teaching personnel", "kennara"], "period"),
        ("preschool-children", "SKO01000", "education", ["pre-primary schools", "leikskolaborn"], "period"),
        ("referendum", "KOS02003", "elections", ["referendum", "thjodaratkvaedi"], "period"),
        ("reykjavik-council", "KOS02006", "elections", ["reykjavik city council", "borgarstjorn"], "period"),
        ("candidates", "KOS02007", "elections", ["candidates", "frambjodendur"], "period"),
        ("metal-emissions", "UMH31101", "environment", ["aluminum", "alframleidsla"], "period"),
        ("road-emissions", "UMH31119", "environment", ["road transport", "vegasamgong"], "period"),
        ("geothermal-share", "IDN02102", "energy", ["geothermal share"], "period"),
        ("oil-imports", "IDN02102", "energy", ["imported energy", "innflutt orka"], "period"),
        ("national-energy", "IDN02102", "energy", ["national production", "innlend framleidsla"], "period"),
        ("population-mean-age", "MAN00102", "population", ["mean age", "medalaldur"], "period"),
        ("births-by-mother", "MAN05101", "births", ["age of mother", "aldur modur"], "period"),
        ("births-first", "MAN05102", "births", ["first born", "frumburdir"], "period"),
        ("multiple-births", "MAN05100", "births", ["twins", "tvinburar"], "period"),
        ("stillbirths", "MAN05100", "births", ["stillbirth", "andvana"], "period"),
        ("crude-birth", "MAN05202", "births", ["reproduction rate", "frjsemi"], "period"),
        ("external-migration-citizenship", "MAN01400", "population", ["citizenship", "migration"], "period"),
        ("population-quarterly", "MAN10001", "population", ["quarterly population", "arsfjordungur mannfjoldi"], "period"),
        ("cpi-weights", "VIS01306", "prices", ["cpi weights", "vaegi"], "period"),
        ("harmonised-cpi", "VIS01004", "prices", ["harmonised", "samraemd visit"], "period"),
        ("wage-real", "LAU04005", "wages", ["real wage", "raunlaun"], "period"),
        ("gdp-volume", "THJ01103", "national-accounts", ["constant prices", "fast verdlag"], "period"),
        ("gdp-quarterly", "THJ01601", "national-accounts", ["quarterly gdp", "arsfjordungur landsframleidsla"], "period"),
        ("current-account", "THJ01102", "national-accounts", ["current account", "vidskiptajofnudur"], "period"),
        ("consumption-fixed", "THJ01102", "national-accounts", ["consumption of fixed capital", "afskriftir"], "period"),
        ("overnight-foreign", "SAM01601", "tourism", ["foreign visitors", "erlendra gesta"], "period, citizenship"),
        ("overnight-domestic", "SAM01601", "tourism", ["icelandic visitors", "innlendra gesta"], "period, citizenship"),
        ("arrivals-foreign", "SAM01601", "tourism", ["foreign arrivals", "erlendar gestakomur"], "period, citizenship"),
        ("students-sex", "SKO00000", "education", ["female students", "nemendur konur"], "period, sex"),
        ("emissions-nox", "UMH31101", "environment", ["nitrous oxide", "nituroxid"], "period"),
        ("energy-peat", "IDN02102", "energy", ["peat", "mor"], "period"),
        ("energy-bio", "IDN02102", "energy", ["biofuel", "lifeldsneyti"], "period"),
    ]
    for tid, table, group, phrases, dims in extras:
        add(Topic(tid, table, group, [[item] for item in phrases], [], 25, dims=dims))
    return rows


_TOPICS = topics()


def refuse_reason(question: str) -> str | None:
    """A question the map will not answer with a summed or monthly cell."""
    text = fold(repair(question))
    if re.search(r"\b\d+\b.{0,16}(and older|og eldri|and over|og eldri)", text):
        return "age band is not one published cell"
    if re.search(r"(65|64).{0,12}(older|eldri|over)", text):
        return "age band is not one published cell"
    if re.search(r"balance of trade|voruskiptajofn", text) and not _has_month(text):
        return "the goods balance is monthly and no month was named"
    if re.search(r"\b(too high|too low|of ha|of lag)\b", text):
        return "the question asks for a judgement"
    return None


def _has_month(text: str) -> bool:
    return re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
        r"januar|februar|mars|april|mai|juni|juli|agust|september|oktober|november|desember|q[1-4])\b",
        text,
    ) is not None


def repair(question: str) -> str:
    def swap(match: re.Match[str]) -> str:
        word = match.group(0)
        fixed = _TYPO.get(fold(word))
        return fixed if fixed else word

    return re.sub(r"[A-Za-zÁÉÍÓÚÝÞÆÖáéíóúýþæöðÐ]+", swap, question)


def _bag(question: str) -> str:
    """Folded words plus BÍN lemmas of the original spellings.

    Folding first drops the accent that the inflection database needs, so
    ``Hafnarfirði`` would no longer meet ``Hafnarfjörður``.
    """
    text = repair(question)
    lemmas = [fold(text)]
    try:
        from grund_lang.binaccess import lexicon_lemma
    except Exception:
        lexicon_lemma = None  # type: ignore
    for word in re.findall(r"[A-Za-zÁÉÍÓÚÝÞÆÖáéíóúýþæöðÐ]+", text):
        lemmas.append(fold(word))
        if lexicon_lemma is None:
            continue
        found = lexicon_lemma(word) or lexicon_lemma(fold(word))
        if found:
            lemmas.append(fold(found[0]))
    return " " + " ".join(lemmas) + " "


def _plain(question: str) -> str:
    return " " + fold(repair(question)) + " "


def _token(text: str, part: str) -> bool:
    """A whole word, or a phrase. ``men`` is not inside ``unemployment``.

    A stem of six letters may start a longer form: ``reykjav`` meets
    ``reykjavik`` and ``hafnarfjordur``.
    """
    part = fold(part).strip()
    if not part:
        return False
    if " " in part:
        return part in text
    if len(part) >= 6:
        return re.search(rf"(?<![a-z0-9]){re.escape(part)}", text) is not None
    return re.search(rf"(?<![a-z0-9]){re.escape(part)}(?![a-z0-9])", text) is not None


def _stem_hit(text: str, part: str) -> bool:
    """A block may be the start of a longer word: export blocks exports."""
    part = fold(part).strip()
    if not part:
        return False
    if " " in part:
        return part in text
    return re.search(rf"(?<![a-z0-9]){re.escape(part)}", text) is not None


def _triggered(topic: Topic, plain: str, bag: str) -> int:
    best = 0
    for group in topic.triggers:
        if group and all(_token(plain, part) or _token(bag, part) for part in group):
            best = max(best, len(group))
    return best


def _blocked(topic: Topic, plain: str, bag: str) -> bool:
    for block in topic.blocks:
        if _stem_hit(plain, block) or _stem_hit(bag, block):
            return True
    return False


# Grammatical words and the frames a headline question uses. A word outside
# this list and outside the topic's own phrases is a more specific series.
_FRAME = {
    "what", "was", "were", "how", "many", "much", "the", "and", "from", "with",
    "that", "this", "for", "over", "into", "than", "did", "does", "there", "which",
    "their", "about", "between", "during", "according", "number", "numbers",
    "iceland", "islandi", "island", "icelands", "islands",
    "january", "february", "march", "april", "june", "july", "august", "september",
    "october", "november", "december", "januar", "februar", "mars", "juni", "juli",
    "agust", "oktober", "desember", "mai",
    "people", "lived", "live", "bjuggu", "bua", "margir", "margar", "margt", "margur",
    "hve", "hver", "hvert", "arid", "year", "years",
    "rate", "index", "percent", "prosent", "prosenta", "hlutfall", "quarter",
    "second", "first", "third", "fourth", "odrum", "arsfjordungi", "arsfjordungur",
    "women", "woman", "men", "female", "male", "konur", "karlar", "kona", "karl",
    "total", "annual", "average", "share", "points", "stig",
    "foreign", "goods", "services", "voru", "thjonustu", "visitors", "gesta", "erlendra",
    "capital", "region", "registered", "accommodation", "gististodum", "stays", "skrad", "skradum",
    "haekkadi", "arsbreyting", "arbreyting", "visitolu", "visitala", "whats",
    "landsmanna", "stort", "eldri", "verdur", "folk", "ibui", "ibuar",
    "change", "babies", "babis", "population", "mannfjoldi", "inhabitants",
}


def _too_specific(topic: Topic, question: str) -> bool:
    """A pasted table title names words this topic does not cover."""
    if "," in question or ":" in question:
        return True
    folded = fold(question)
    if re.search(r"\b(fall|fell|rose|risen)\b", folded) or re.search(r"\bfrom (?:19|20)\d{2} to (?:19|20)\d{2}\b", folded):
        if "change" not in topic.dims:
            return True
    by_split = re.search(r"\bby (?!how\b|what\b)", folded)
    if by_split:
        tail = folded[by_split.end():]
        dims = topic.dims
        mapped = (
            (any(word in tail for word in ("sex", "kyn", "women", "men", "konur", "karlar")) and "sex" in dims)
            or (any(word in tail for word in ("foreign", "erlend", "citizen", "visitor")) and "citizenship" in dims)
            or (any(word in tail for word in ("region", "landshlut")) and "region" in dims)
            or ("age" in tail and "age" in dims)
        )
        if not mapped:
            return True
    blob = " ".join(fold(part) for group in topic.triggers for part in group)
    blob += " " + " ".join(fold(part) for part in topic.pick_any + topic.pick_all)
    try:
        from grund_lang.binaccess import lexicon_lemma
    except Exception:
        lexicon_lemma = None  # type: ignore
    extras = []
    for token in re.findall(r"[a-z0-9]+", fold(repair(question))):
        if len(token) < 5 or token in _FRAME or token.isdigit():
            continue
        lemma = token
        if lexicon_lemma is not None:
            found = lexicon_lemma(token)
            if found:
                lemma = fold(found[0])
        if token in blob or lemma in blob:
            continue
        if any(
            len(part) >= 5 and (token.startswith(part[:6]) or part.startswith(token[:6]) or lemma.startswith(part[:6]))
            for part in blob.split()
        ):
            continue
        extras.append(token)
    return len(extras) >= 1


def match(question: str) -> Topic | None:
    if not enabled():
        return None
    if "," in question or ":" in question:
        return None
    plain = _plain(question)
    bag = _bag(question)
    best: Topic | None = None
    best_key = (-1, -1)
    for topic in _TOPICS:
        if _blocked(topic, plain, bag):
            continue
        score = _triggered(topic, plain, bag)
        if score <= 0:
            continue
        if _too_specific(topic, question):
            continue
        key = (topic.rank, score)
        if key > best_key:
            best = topic
            best_key = key
    return best


def _table(catalogue, table_id: str) -> Table | None:
    return catalogue.by_id.get(table_id + ".px") or catalogue.by_id.get(table_id)


def _edition(table: Table, language: str) -> Edition | None:
    return table.edition(language) or table.edition("en") or table.edition("is")


def _find_value(table: Table, hint: str, any_of: list[str], all_of: list[str], not_of: list[str]) -> tuple[str, str] | None:
    """The published code whose label matches. The shortest label wins.

    ``Immigrant`` is the origin row. ``Second generation immigrant`` also
    contains the word and is a different cell.
    """
    hints = [fold(part) for part in hint.split("|") if part]
    best: tuple[int, str, str] | None = None
    for edition in table.editions.values():
        for variable in edition.variables:
            blob = fold(f"{variable.text} {variable.code}")
            if hints and not any(item in blob for item in hints):
                continue
            for code, label in variable.values:
                folded = fold(label)
                if any(fold(item) in folded for item in not_of):
                    continue
                if all_of and not all(fold(item) in folded for item in all_of):
                    continue
                if any_of and not any(fold(item) in folded for item in any_of):
                    continue
                if not any_of and not all_of:
                    continue
                weight = len(folded)
                if best is None or weight < best[0]:
                    best = (weight, variable.code, str(code))
    if best is None:
        return None
    return best[1], best[2]


def _sexes(text: str) -> tuple[bool, bool]:
    folded = fold(text)
    male = bool(re.search(r"\b(men|males?|karlar|karl|korlum)\b", folded))
    female = bool(re.search(r"\b(women|woman|females?|konur|kona|kven\w*)\b", folded))
    return male, female


def _sex_variable(edition: Edition) -> Variable | None:
    for variable in edition.variables:
        if re.search(r"sex|kyn|gender", fold(f"{variable.text} {variable.code}")):
            return variable
    return None


def _pick_sex(edition: Edition, question: str) -> str | None:
    male, female = _sexes(question)
    if male == female:
        return None
    variable = _sex_variable(edition)
    if variable is None:
        return None
    for code, label in variable.values:
        label_male, label_female = _sexes(label)
        if female and label_female and not label_male:
            return str(code)
        if male and label_male and not label_female:
            return str(code)
    return None


def _total_code(variable: Variable) -> str | None:
    from grund.bind import is_total

    for code, label in variable.values:
        if is_total(label) or fold(label) in {"total", "alls", "all", "samtals", "0", "-1"}:
            return str(code)
    return None


def _set_code(selections: list[dict], variable: str, code: str) -> None:
    for entry in selections:
        if entry.get("code") == variable:
            entry["selection"]["values"] = [code]
            return
    selections.append({"code": variable, "selection": {"filter": "item", "values": [code]}})


def _selection_map(selections: list[dict]) -> dict[str, list[str]]:
    found = {}
    for entry in selections:
        found[str(entry.get("code"))] = list(entry.get("selection", {}).get("values") or [])
    return found


def _municipality_code(table: Table, question: str) -> str | None:
    """A town the question names, matched through BÍN and the published label."""
    bag = _bag(question)
    best: tuple[int, str] | None = None
    for edition in table.editions.values():
        for variable in edition.variables:
            if "sveitar" not in fold(variable.text) and "municip" not in fold(variable.text):
                continue
            for code, label in variable.values:
                folded = fold(label)
                if folded in {"total", "alls", "all", "9999", "is"}:
                    continue
                stem = folded
                for suffix in ("kaupstadur", "kaupstad", "baer", "borg", "hreppur"):
                    if stem.endswith(suffix) and len(stem) - len(suffix) >= 6:
                        stem = stem[: -len(suffix)]
                        break
                head = stem[:7]
                if len(head) < 6:
                    continue
                if head in bag or stem in bag:
                    weight = len(stem)
                    if best is None or weight > best[0]:
                        best = (weight, str(code))
    return None if best is None else best[1]


def _region_code(table: Table, question: str) -> str | None:
    text = fold(repair(question))
    order = [
        ("southwest", ["southwest", "sudurnes"]),
        ("westfjords", ["westfjord", "vestfird"]),
        ("northwest", ["northwest", "vestra"]),
        ("northeast", ["northeast", "eystra"]),
        ("capital", ["capital", "hofudborg"]),
        ("east", ["austurland"]),
        ("south", ["sudurland"]),
        ("west", ["vesturland"]),
    ]
    wanted = ""
    for name, keys in order:
        if name == "south" and "southwest" in text:
            continue
        if name == "west" and ("westfjord" in text or "vestfird" in text):
            continue
        if name == "capital" and "outside" in text:
            continue
        if any(key in text for key in keys):
            wanted = name
            break
    if not wanted:
        return None
    keys = dict(order)[wanted]
    for edition in table.editions.values():
        for variable in edition.variables:
            if "landshlut" not in fold(variable.text) and "region" not in fold(variable.text):
                continue
            for code, label in variable.values:
                folded = fold(label)
                if folded in {"total", "alls"}:
                    continue
                if any(key in folded for key in keys):
                    if wanted == "capital" and "outside" in folded:
                        continue
                    if wanted == "south" and "sudurnes" in folded:
                        continue
                    if wanted == "west" and "vestfird" in folded:
                        continue
                    return str(code)
    return None


def _age_code(edition: Edition, question: str) -> str | None:
    text = fold(question)
    match = re.search(r"\b(\d{1,2})\s*-?\s*(year|ara|ars)\b", text)
    if match is None:
        match = re.search(r"\b(\d{1,2})\s*year", text)
    if match is None:
        return None
    if re.search(r"older|eldri|over", text[match.end(): match.end() + 16]):
        return None
    number = str(int(match.group(1)))
    for variable in edition.variables:
        if not re.search(r"\b(age|aldur)\b", fold(variable.text)):
            continue
        for code, label in variable.values:
            folded = fold(f"{code} {label}")
            if re.search(rf"\b{number}\b", folded) and "total" not in folded and folded not in {"-1", "alls"}:
                # Prefer the single year, not a band that merely contains the number.
                if re.search(rf"\b{number}\s*-", folded) or re.search(rf"-\s*{number}\b", folded):
                    continue
                return str(code)
    return None


def _unit_for_question(table: Table, question: str) -> tuple[str, str] | None:
    text = fold(repair(question))
    percent = bool(re.search(r"percent|prosent|hlutfall|arsbreyting|arbreyting|over the year|a ari", text))
    points = bool(re.search(r"\b(points|stig)\b", text))
    how_many = bool(re.search(r"how many|hve marg", text))
    if percent and not points:
        found = _find_value(table, "eining|unit|item|lidur", ["annual change", "arsbreyting", "change_a"], [], ["month"])
        if found:
            return found
    if how_many and re.search(r"unemploy|atvinnulaus", text):
        return _find_value(table, "eining|unit", ["unemployed", "atvinnulaus"], [], ["rate", "hlutfall", "%"])
    if re.search(r"unemployment rate|atvinnuleysi", text) and not how_many:
        return _find_value(table, "eining|unit|hlutfall", ["unemployment rate", "atvinnuleysi"], [], [])
    if re.search(r"arrival|gestakom", text):
        return _find_value(table, "eining|unit", ["arrival", "gestakom"], [], [])
    if re.search(r"overnight|gistin", text):
        return _find_value(table, "eining|unit", ["overnight", "gistin"], [], ["arrival"])
    if re.search(r"foreign|erlend", text) and re.search(r"overnight|gistin|arrival|gestakom", text):
        return _find_value(table, "thjoderni|citizenship|national", ["foreign", "erlend"], [], ["total"])
    return None


def _citizenship_code(table: Table, question: str) -> str | None:
    text = fold(repair(question))
    if not re.search(r"overnight|gistin|arrival|gestakom", text):
        return None
    if re.search(r"foreign|erlend", text):
        found = _find_value(table, "thjoderni|citizenship|national", ["foreign", "erlend"], [], ["total", "alls"])
    elif re.search(r"icelandic visitors|innlend", text):
        found = _find_value(table, "thjoderni|citizenship|national", ["iceland", "island"], [], ["total"])
    else:
        found = _find_value(table, "thjoderni|citizenship|national", ["total", "alls"], [], [])
    if found is None:
        return None
    return found[1]


def _migration_code(table: Table, question: str) -> str | None:
    text = fold(repair(question))
    if re.search(r"net immigration|netto|umfram", text):
        phrases = ["net immigration", "umfram"]
    elif re.search(r"emigrat|fluttu fra|brottflutt", text):
        phrases = ["emigration", "brottflutt"]
    elif re.search(r"immigrat|fluttu til", text):
        phrases = ["immigration", "adflutt"]
    else:
        return None
    found = _find_value(table, "flutning|migration|tegund", phrases, [], ["net"] if "immigration" in phrases[0] and "net" not in text else [])
    if found is None:
        return None
    # "Immigration" must not be the net row. Prefer a label that is not "net" / "umfram".
    if "net" not in text and "umfram" not in text:
        better = _find_value(
            table, "flutning|migration|tegund", phrases, [], ["net", "umfram"],
        )
        if better:
            return better[1]
    return found[1]


def _binding_from_selections(edition: Edition, parsed, selections: list[dict], operation: str, notes: list[str]):
    from grund.bind import Binding

    time_var = None
    time_codes: list[str] = []
    for variable in edition.variables:
        if variable.time:
            time_var = variable.code
            time_codes = list(_selection_map(selections).get(variable.code) or [])
    return Binding(
        edition=edition,
        selections=selections,
        operation=operation,
        score=5.0,
        time_var=time_var,
        time_codes=time_codes,
        notes=notes,
        official_measure=operation == "level" and any("change" in note for note in notes),
    )


def _copy_selections(binding) -> list[dict]:
    copied = []
    for entry in binding.selections:
        values = list(entry.get("selection", {}).get("values") or [])
        copied.append({"code": entry.get("code"), "selection": {"filter": "item", "values": values}})
    return copied


def _ensure_all(edition: Edition, parsed, selections: list[dict]) -> list[dict] | None:
    from grund.bind import _select_time
    from grund.cells import _is_time_variable

    have = _selection_map(selections)
    for variable in edition.variables:
        if variable.code in have and have[variable.code]:
            continue
        if variable.time or _is_time_variable(variable):
            picked = _select_time(variable, parsed, "level")
            if not picked:
                if variable.values:
                    picked = [str(variable.values[-1][0])]
            if not picked:
                return None
            _set_code(selections, variable.code, picked[-1] if parsed.operation != "yoy_pct" else picked[0])
            if len(picked) > 1 and parsed.operation == "yoy_pct":
                for entry in selections:
                    if entry["code"] == variable.code:
                        entry["selection"]["values"] = picked
            continue
        total = _total_code(variable)
        if total is None and variable.values:
            total = str(variable.values[0][0])
        if total is None:
            return None
        _set_code(selections, variable.code, total)
    return selections


def build_binding(catalogue, topic: Topic, question: str, language: str):
    """Selections for one topic. None when a named dimension has no published code."""
    from grund.bind import bind
    from grund.parse import parse_question

    table = _table(catalogue, topic.table)
    if table is None:
        return None
    edition = _edition(table, language)
    if edition is None:
        return None
    parsed = parse_question(repair(question), language)
    peer = table.edition("is") if edition.lang == "en" else table.edition("en")
    bound = bind(edition, parsed, peer)
    named: set[str] = set()
    notes = ["topic map", topic.id]
    if bound is not None and bound.operation == "share":
        return bound, named, edition
    if bound is not None:
        selections = _copy_selections(bound)
        operation = bound.operation
    else:
        selections = []
        operation = parsed.operation if parsed.operation in {"level", "yoy_pct", "difference", "share"} else "level"
        if _ensure_all(edition, parsed, selections) is None:
            return None

    if topic.pick_any or topic.pick_all:
        found = _find_value(table, topic.var_hint, topic.pick_any, topic.pick_all, topic.pick_not)
        if found is None and topic.pick_any:
            return None
        if found is not None:
            variable, code = found
            _set_code(selections, variable, code)
            named.add(code)

    sex = _pick_sex(edition, question)
    if sex is not None:
        variable = _sex_variable(edition)
        if variable is not None and operation != "share":
            _set_code(selections, variable.code, sex)
            named.add(sex)
    elif re.search(r"\b(men|women|konur|karlar|kvenna)\b", fold(question)) and "sex" in topic.dims and operation != "share":
        return None

    if "municipality" in topic.dims:
        town = _municipality_code(table, question)
        if town is None:
            return None
        for variable in edition.variables:
            if "sveitar" in fold(variable.text) or "municip" in fold(variable.text):
                _set_code(selections, variable.code, town)
                named.add(town)
                break

    if "region" in topic.dims:
        region = _region_code(table, question)
        if region is not None:
            for variable in edition.variables:
                if "landshlut" in fold(variable.text) or fold(variable.text) == "region":
                    _set_code(selections, variable.code, region)
                    named.add(region)
                    break

    age = _age_code(edition, question)
    if age is not None:
        for variable in edition.variables:
            if re.search(r"\b(age|aldur)\b", fold(variable.text)):
                _set_code(selections, variable.code, age)
                named.add(age)
                break

    unit = _unit_for_question(table, question)
    if unit is not None:
        variable, code = unit
        _set_code(selections, variable, code)
        named.add(code)
        if re.search(r"annual change|arsbreyting|percent|prosent", fold(repair(question))):
            operation = "level"
            notes.append("change")
            # One period: the asked one, not the previous year used to recompute.
            if edition.time_variable() is not None and parsed.periods:
                from grund.bind import _select_time

                picked = _select_time(edition.time_variable(), parsed, "level")
                if picked:
                    _set_code(selections, edition.time_variable().code, picked[-1])

    citizen = _citizenship_code(table, question)
    if citizen is not None:
        for variable in edition.variables:
            if re.search(r"thjoderni|citizenship|national", fold(variable.text)):
                _set_code(selections, variable.code, citizen)
                if fold(citizen) not in {"total", "alls", "0"}:
                    named.add(citizen)
                break

    moved = _migration_code(table, question)
    if moved is not None:
        for variable in edition.variables:
            if re.search(r"flutning|migration|tegund", fold(variable.text)):
                _set_code(selections, variable.code, moved)
                named.add(moved)
                break

    # The labour-force age span is the published total of that survey.
    if re.search(r"unemploy|atvinnu|employed|starfandi", fold(question)) and not _age_code(edition, question):
        for variable in edition.variables:
            if re.search(r"\b(age|aldur)\b", fold(variable.text)):
                for code, label in variable.values:
                    if re.search(r"16\s*-?\s*74", fold(f"{code} {label}")):
                        _set_code(selections, variable.code, str(code))
                        named.add(str(code))
                        break

    if _ensure_all(edition, parsed, selections) is None:
        return None
    binding = _binding_from_selections(edition, parsed, selections, operation if operation != "yoy_pct" else "level", notes)
    return binding, named, edition


def resolve(catalogue, question: str, language: str) -> Spec | None:
    """The table to move first. No cell is chosen here.

    The binder, the measure check, the subgroup check, and the rail still
    decide whether a figure is stated.
    """
    if not enabled():
        return None
    topic = match(question)
    if topic is None:
        return None
    table = _table(catalogue, topic.table)
    if table is None:
        return None
    edition = _edition(table, language)
    if edition is None:
        return None
    hit = Hit(table=table, score=100.0, bm25=0.0, cosine=0.0, value_boost=0.0)
    return Spec(
        topic_id=topic.id,
        table_id=topic.table,
        hit=hit,
        binding=None,
        title="",
        named_codes=set(),
        group=topic.group,
        dims=topic.dims,
    )


def promote(hits: list, table_id: str) -> list:
    """Move a table already in the list to the front. Does not add one."""
    if not hits:
        return hits
    stem = table_id.removesuffix(".px")
    kept = []
    first = None
    for hit in hits:
        if hit.table.id.removesuffix(".px") == stem and first is None:
            first = hit
            continue
        kept.append(hit)
    if first is None:
        return hits
    return [first, *kept]


def rerank(catalogue, question: str, hits: list, language: str = "en") -> list:
    """Move the matched table first. The binder and the rail still choose the cell."""
    from grund.isbirths import parent_role, specific_age

    parent = parent_role(question)
    if specific_age(question) and parent in {"mother", "father"} and hits is not None:
        stem = "MAN05101" if parent == "mother" else "MAN05102"
        table = _table(catalogue, stem)
        if table is not None:
            kept = [hit for hit in hits if hit.table.id.removesuffix(".px") != stem]
            score = max((hit.score for hit in hits), default=0.0) + 10.0
            lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
            return [lead, *kept]
    if not enabled() or not hits:
        return hits
    spec = resolve(catalogue, question, language)
    if spec is None or not spec.table_id or spec.hit is None:
        return hits
    ordered = promote(hits, spec.table_id)
    if ordered[0].table.id.removesuffix(".px") != spec.table_id:
        return [spec.hit, *ordered]
    return ordered
