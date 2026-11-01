"""Choose the headline series when the two paths name different tables.

Off unless GRUND_SERIES_PICK=1. A path is preferred only when both paths
stated a figure and one of them is the series the question named. A
lookalike is not promoted on its own.
"""

from __future__ import annotations

import os
import re

from grund_index.textutil import fold

_HEADCOUNT = re.compile(
    r"(population|mannfjold|ibua|ibuar|inhabitants|residents|headcount|"
    r"fjolksfjold|heima|bjuggu|bua\b|people (live|lived)|how many people|"
    r"hve margir|hve margar)"
)
_NOT_HEADCOUNT = (
    "atvinnu", "unemploy", "jobless", "vinnuafl", "labour", "labor",
    "gistin", "tourist", "ferdam", "export", "import", "utflut", "innflut",
    "landsframleid", "gdp", "visitala", "laun", "faedd", "birth",
    "innflytj", "immigrant", "flutt", "migrat",
)
_PLACE = (
    "hofudborgarsvaed", "capital region", "capital area",
    "vesturland", "austurland", "sudurland", "nordurland",
    "vestfird", "westfjord", "west region", "east iceland", "the east",
    "the west", "the south", "northeast", "northwest", "southwest",
    "hafnarfj", "kopavog", "akureyr", "reykjavik", "gardabae", "reykjanesb", "arborg",
)
_LOOKALIKE_PREFIX = ("VIN", "UTA", "THJ07", "VIS06", "SAM08", "MAN102", "MAN011")
_POPULATION_OK = ("MAN00000", "MAN00101", "MAN0200", "MAN032", "MAN030")


def enabled() -> bool:
    return os.environ.get("GRUND_SERIES_PICK", "").strip().lower() in {"1", "true", "yes"}


def preferred_path(question: str, ranker: dict, hybrid: dict) -> str | None:
    """'ranker' or 'hybrid' when that path is the headline series."""
    if not enabled():
        return None
    text = fold(question or "")
    if _stated(ranker) and _stated(hybrid):
        if _better(text, ranker, hybrid):
            return "ranker"
        if _better(text, hybrid, ranker):
            return "hybrid"
    return None


def capital_guard(question: str, ranker: dict, hybrid: dict) -> str | None:
    """Keep the capital city off the capital-region row.

    'The capital' and 'höfuðborgin' name Reykjavík. 'Capital region' and
    'höfuðborgarsvæðið' name the region. When the city was asked and a path
    stated the region, use the Reykjavík municipality path, or refuse when
    neither path has that municipality.
    """
    if not enabled():
        return None
    if _capital_scope(fold(question or "")) != "city":
        return None
    city = [name for name, result in (("ranker", ranker), ("hybrid", hybrid)) if _is_reykjavik_cell(result)]
    region = [name for name, result in (("ranker", ranker), ("hybrid", hybrid)) if _is_capital_region_cell(result)]
    if not region:
        return None
    if city:
        return city[0]
    return "refuse"


def _stated(result: dict | None) -> bool:
    return bool(result) and not result.get("refused") and result.get("value") not in (None, "")


def _stem(result: dict) -> str:
    return str(result.get("table_id") or "").removesuffix(".px")


def _blob(result: dict) -> str:
    parts = [_stem(result)]
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    for cell in source.get("cells") or []:
        if isinstance(cell, dict):
            parts.append(str(cell.get("key") or ""))
            parts.append(str(cell.get("coords") or ""))
            parts.append(str(cell.get("labels") or ""))
    pair = result.get("path_pair") if isinstance(result.get("path_pair"), dict) else {}
    # Cells travel on the result claims for a finished path.
    for claim in result.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if isinstance(cell, dict):
                parts.append(str(cell.get("coords") or ""))
                parts.append(str(cell.get("key") or ""))
                parts.append(str(cell.get("labels") or ""))
    return fold(" ".join(parts))


def _headcount(text: str) -> bool:
    if not _HEADCOUNT.search(text):
        return False
    return not any(word in text for word in _NOT_HEADCOUNT)


def _place(text: str) -> str | None:
    for stem in _PLACE:
        if stem in text:
            return stem
    return None


def _population_table(stem: str) -> bool:
    if stem in {"MAN00102", "MAN01102", "MAN01400", "MAN10200"}:
        return False
    return stem.startswith(_POPULATION_OK)


def _lookalike_table(stem: str) -> bool:
    return stem.startswith(_LOOKALIKE_PREFIX) or stem in {"THJ01103", "THJ07000"}


def _better(text: str, candidate: dict, other: dict) -> bool:
    if not _headline(text, candidate, other):
        return False
    # A Total or Alls cell is the whole group. It is not the sex, the age
    # band, or the place the question named.
    if _total_for_named_subgroup(text, candidate):
        return False
    return True


def _headline(text: str, candidate: dict, other: dict) -> bool:
    cand = _stem(candidate)
    oth = _stem(other)
    if cand == oth:
        return False
    if _headcount(text) and _population_table(cand) and _lookalike_table(oth):
        scope = _capital_scope(text)
        if scope == "city":
            return _is_reykjavik_cell(candidate)
        if scope == "region":
            return _is_capital_region_cell(candidate)
        place = _place(text)
        if place is None:
            # A resident count beats a labour-force or trade table. Mean age
            # is not in that lookalike list, so it is not promoted over.
            return True
        blob = _blob(candidate)
        if place in blob or place.replace(" ", "") in blob:
            return True
        # English "the south" is the region label "south".
        if place == "the south" and "south" in blob and "southwest" not in blob:
            return True
        return False
    if _asks_current_gdp(text) and cand == "THJ01102" and _gdp_lookalike(oth):
        return True
    if _asks_cpi(text) and cand.startswith("VIS010") and oth.startswith("THJ07"):
        return True
    if _asks_wage_index(text) and cand == "LAU04000" and oth == "LAU04001":
        return True
    if _asks_external(text) and cand.startswith("MAN014") and oth.startswith("MAN011"):
        return True
    if _asks_unemployment(text) and cand in {"VIN00920", "VIN00921"} and oth in {"VIN00910", "VIN00911"}:
        return True
    return False


_MALE = re.compile(r"\b(karlkyns|karlmenn|karlar|drengir|drengur|males?|boys?|men|karl)\b")
_FEMALE = re.compile(r"\b(kvenkyns|kvenna|konur|kona|stulkur|stulka|females?|women|woman|girls?)\b")
_AGE_BAND = re.compile(
    r"(\b\d{1,3}\s*-\s*year|\b\d{1,3}\s+(ara|ar|years|year)\b|\b(eldri|yngri)\b|"
    r"\band older\b|\bor older\b|\band over\b|\bog eldri\b)"
)
_TOTAL_VALUE = {
    "total", "totals", "alls", "samtals", "all", "allt",
    "allt landid", "oll landid", "whole country", "entire country",
    "all regions", "whole county", "landid allt",
    "males and females", "karlar og konur", "both sexes", "all ages",
}
_COUNTRY_WORD = {
    "iceland", "island", "islandi", "islands", "islandss", "landsins",
    "landid", "landinu", "landi",
}
_TOWN_SUFFIX = ("baer", "borg", "fjord", "fird", "vik", "nes", "hrepp", "stad", "svaed")


def _names_one_sex(text: str) -> bool:
    male = bool(_MALE.search(text))
    female = bool(_FEMALE.search(text))
    if male and female:
        return False
    return male or female


def _names_age(text: str) -> bool:
    if _AGE_BAND.search(text):
        return True
    return bool(re.search(r"\b\d{1,2}\s*-\s*\d{1,2}\b", text) and re.search(r"\b(age|aldur|ara|years|year)\b", text))


def _names_place(text: str) -> bool:
    if _capital_scope(text) or _place(text):
        return True
    for token in re.findall(r"[a-z0-9]+", text):
        if len(token) < 6 or token in _COUNTRY_WORD:
            continue
        for suffix in _TOWN_SUFFIX:
            at = token.rfind(suffix)
            if at >= 4:
                return True
    return False


def _dim_kind(key: str) -> str:
    name = fold(key)
    if any(piece in name for piece in ("kyn", "sex", "gender")):
        return "sex"
    if any(piece in name for piece in ("aldur", "age")):
        return "age"
    if any(piece in name for piece in (
        "sveitarfelag", "municip", "landshlut", "landsvaed", "region",
        "postnumer", "postcode", "hverfi", "district", "byggd", "localit",
        "urban", "thettbyl",
    )):
        return "place"
    return ""


def _is_total_value(value: str) -> bool:
    folded = fold(value).strip(" .:-")
    return folded in _TOTAL_VALUE


def _dim_pairs(result: dict) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for cell in _result_cells(result):
        labels = cell.get("labels") or {}
        if isinstance(labels, dict):
            pairs.extend((str(key), str(value)) for key, value in labels.items())
        elif isinstance(labels, list):
            for item in labels:
                if isinstance(item, dict):
                    key = item.get("variable_text") or item.get("variable") or ""
                    pairs.append((str(key), str(item.get("label") or "")))
        coords = cell.get("coords") or {}
        if isinstance(coords, dict):
            pairs.extend((str(key), str(value)) for key, value in coords.items())
    return pairs


def _result_cells(result: dict) -> list[dict]:
    found: list[dict] = []
    for claim in result.get("claims") or []:
        if isinstance(claim, dict):
            found.extend(cell for cell in (claim.get("cells") or []) if isinstance(cell, dict))
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    found.extend(cell for cell in (source.get("cells") or []) if isinstance(cell, dict))
    return found


def _code_only(value: str) -> bool:
    """A PxWeb code such as 9999 or -1. Short words such as Konur are labels."""
    if _is_total_value(value):
        return False
    return bool(re.fullmatch(r"[0-9-]{1,6}", fold(value).strip()))


def _stated_values(values: list[str]) -> list[str]:
    textual = [value for value in values if not _code_only(value)]
    return textual or values


def _total_for_named_subgroup(text: str, result: dict) -> bool:
    grouped: dict[str, list[str]] = {"sex": [], "age": [], "place": []}
    for key, value in _dim_pairs(result):
        kind = _dim_kind(key)
        if kind:
            grouped[kind].append(value)
    checks = (
        ("sex", _names_one_sex(text)),
        ("age", _names_age(text)),
        ("place", _names_place(text)),
    )
    for kind, named in checks:
        stated = _stated_values(grouped[kind])
        if named and stated and all(_is_total_value(value) for value in stated):
            return True
    return False


def _capital_scope(text: str) -> str | None:
    """'region' for the capital area, 'city' for Reykjavík, else nothing.

    The region phrase is tested first. 'The capital region' contains
    'the capital' and is still the region.
    """
    if any(phrase in text for phrase in ("capital region", "capital area", "hofudborgarsvaed")):
        return "region"
    if re.search(r"\bthe capital\b", text) or "hofudborg" in text:
        return "city"
    return None


def _place_values(result: dict) -> list[str]:
    return [value for key, value in _dim_pairs(result) if _dim_kind(key) == "place"]


def _is_capital_region_cell(result: dict) -> bool:
    if not _stated(result):
        return False
    for value in _stated_values(_place_values(result)):
        folded = fold(value).strip()
        if folded in {"capital region", "capital area"} or folded.startswith("hofudborgarsvaed"):
            return True
    return False


def _is_reykjavik_cell(result: dict) -> bool:
    """The municipality or its district total, not the capital region."""
    if not _stated(result) or _is_capital_region_cell(result):
        return False
    if _stem(result).startswith("MAN03270"):
        return True
    blob = _blob(result)
    return "reykjavik" in blob


def _asks_current_gdp(text: str) -> bool:
    if any(word in text for word in ("fostu", "constant price", "kaupmatt", "purchasing power", "ppp")):
        return False
    return any(word in text for word in ("gdp", "landsframleid", "gross domestic", "verg landsframleid"))


def _gdp_lookalike(stem: str) -> bool:
    return stem in {"THJ01103", "THJ07000"} or stem.startswith(("THJ060", "VIS061"))


def _asks_cpi(text: str) -> bool:
    if any(word in text for word in ("spa", "forecast", "framreikn")):
        return False
    return any(word in text for word in ("neysluverd", "consumer price", "cpi"))


def _asks_wage_index(text: str) -> bool:
    if any(word in text for word in ("basic wage", "grunnvis", "2015")):
        return False
    return "launavisit" in text or "wage index" in text


def _asks_external(text: str) -> bool:
    return any(word in text for word in ("til islands", "to iceland", "hingad", "erlendis", "from abroad", "adflutt"))


def _asks_unemployment(text: str) -> bool:
    if any(word in text for word in ("atvinnuthatt", "activity rate")):
        return False
    return any(word in text for word in ("atvinnuleys", "unemploy", "jobless"))
