"""Refuse a total whose measure is not the one the question named.

Off unless ``GRUND_MEASURE_GUARD`` is set. A death, a foreign-citizen
count, a basic wage index, an unemployment rate, and a month of goods
exports are not the national population, the 1989 wage index, a headcount,
or the annual national accounts. The same check sends a headline goods
month to the trade-flow table, a national sex headcount to the sex-and-age
table, compulsory-school pupils to the pupil table, and the euro's annual
average to that currency's all-year cell.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_MONTHS = (
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "januar", "februar", "mars",
    "mai", "juni", "juli", "agust", "september", "oktober", "november", "desember",
)
_COMMODITY = (
    "fish", "marine", "aluminium", "aluminum", "sjavar", "fisk", "al ",
    "farm", "landbunad", "industry", "idnad",
)
_PLACES = (
    "reykjav", "kopavog", "akureyr", "hafnarfj", "gardabae", "mosfell", "arborg",
    "sveitarfel", "municip", "hofudborg", "capital", "sudurnes", "vestfird",
    "nordurland", "austurland", "vesturland", "sudurland", "westfjord",
    "northeast", "northwest", "southwest", "landshlut",
)
_POPULATION_TABLES = {"MAN00000", "MAN00101", "MAN02007", "MAN03200", "MAN03250", "MAN03260"}


def enabled() -> bool:
    return os.environ.get("GRUND_MEASURE_GUARD", "0").strip().lower() in {"1", "on", "true", "yes"}


def _text(question: str) -> str:
    return fold(question or "")


def _month(text: str) -> bool:
    return re.search(r"\b(" + "|".join(_MONTHS) + r")\b", text) is not None


def _commodity(text: str) -> bool:
    return any(mark in text for mark in _COMMODITY)


def _goods(text: str) -> bool:
    if "voruutflut" in text or "voruinnflut" in text:
        return True
    goods = "voru" in text or re.search(r"\bgoods\b", text) is not None
    flow = "utflutn" in text or "innflutn" in text or "export" in text or "import" in text
    return goods and flow


def foreign_citizens(question: str) -> bool:
    text = _text(question)
    if "foreign citizen" in text:
        return True
    return "erlend" in text and "rikisborg" in text


def register_question(question: str) -> bool:
    text = _text(question)
    return "population register" in text or "skradur mannfjold" in text or "skrad mannfjold" in text


def basic_wage(question: str) -> bool:
    if not enabled():
        return False
    text = _text(question)
    return "basic wage" in text or "grunnlaun" in text


def monthly_goods(question: str) -> bool:
    """A named month of goods exports or imports is not the annual accounts."""
    if not enabled():
        return False
    text = _text(question)
    return _goods(text) and _month(text) and not _commodity(text)


def kang_missed_death(question: str) -> bool:
    """``létust`` is not lemmatized to ``deyja``, so the kang guard does not see it."""
    if not enabled():
        return False
    return re.search(r"\bletust\b", _text(question)) is not None


def population_measure_miss(question: str) -> bool:
    """Foreign citizens, the register, and pupils are not the sex-and-age total.

    Deaths, marriages, hotel beds, and emigrants are ``GRUND_IS_KANG_GUARD``,
    except the verb ``létust``, which that guard's lemmatizer misses.
    """
    if not enabled():
        return False
    if kang_missed_death(question) or foreign_citizens(question) or register_question(question):
        return True
    text = _text(question)
    return re.search(r"\b(pupils?|nemendur|nemendum)\b", text) is not None


def unemployment_is_rate(text: str) -> bool:
    """``hlutfall atvinnulausra`` is the rate, not the estimated headcount."""
    if not enabled():
        return False
    folded = fold(text or "")
    return "hlutfall" in folded or re.search(r"\brate\b", folded) is not None or "atvinnuleys" in folded


def _two_asks(text: str) -> bool:
    return any(mark in text for mark in ("and what", "og hver", "og hvert", "og hvad"))


def national_sex(question: str) -> bool:
    """One sex, a national headcount. Not a gap, a rate, or unemployment."""
    text = _text(question)
    if _two_asks(text):
        return False
    if any(mark in text for mark in ("atvinnu", "unemploy", "munad", "munur", "difference", "hlutfall", "percent")):
        return False
    women = re.search(r"\b(konur|kona|kvenna|women|woman|females?)\b", text) is not None
    men = re.search(r"\b(karlar|karl|men|males?)\b", text) is not None
    if women == men:
        return False
    if not re.search(r"\b(hve marg\w*|hversu marg\w*|how many|bjuggu|bua|lived|live|lives)\b", text):
        return False
    if re.search(r"\b(island\w*|iceland\w*)\b", text) is None and "landsins" not in text:
        return False
    if any(mark in text for mark in _PLACES):
        return False
    return True


def generic_pupils(question: str) -> bool:
    text = _text(question)
    if re.search(r"\b(nemendur|nemendum|pupils?)\b", text) is None:
        return False
    if "grunnskol" not in text and "compulsory" not in text:
        return False
    if any(mark in text for mark in ("einkaskol", "seriskol", "rekstrarform", "private school", "special school")):
        return False
    return True


def _asks_euro(text: str) -> bool:
    return "evru" in text or re.search(r"\b(evra|euro|eur)\b", text) is not None


def _asks_dollar(text: str) -> bool:
    return re.search(r"\b(usd|dollar|dalur|dal|dalins)\b", text) is not None or "bandarikjadal" in text


def _exchange(text: str) -> bool:
    return "gengi" in text or "solugengi" in text or "exchange rate" in text


def _year(question: str) -> bool:
    return re.search(r"(?:19|20)\d{2}", question or "") is not None


def value_code(variable, question: str, language: str | None, title: str) -> str | None:
    """The cell the measure names, when the guard is on."""
    if not enabled():
        return None
    text = _text(question)
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    title_f = fold(title or "")
    values = list(getattr(variable, "values", []) or [])
    if "gjaldmidil" in blob or re.search(r"\bcurrency\b", blob):
        if _asks_euro(text) and not _asks_dollar(text):
            for code, label in values:
                folded = fold(str(label or ""))
                if "evra" in folded or re.search(r"\beuro\b", folded):
                    return str(code)
        return None
    if re.search(r"\b(manudur|month)\b", blob):
        if _exchange(text) and _year(question) and not _month(text):
            for code, label in values:
                folded = fold(str(label or ""))
                if folded in {"allt arid", "all year"} or "allt arid" in folded:
                    return str(code)
        return None
    if generic_pupils(question) and ("fjoldi" in blob or re.search(r"\bnumber\b", blob)):
        for code, label in values:
            folded = fold(str(label or ""))
            if "nemend" in folded or "pupil" in folded:
                return str(code)
        return None
    if register_question(question) and ("eining" in blob or re.search(r"\bunit\b", blob)):
        if "lykiltol" not in title_f and "key figure" not in title_f:
            return None
        for code, label in values:
            folded = fold(str(label or ""))
            if any(mark in folded for mark in ("increase", "aukning", "prosent", "%", "adjustment", "leidrett")):
                continue
            if ("mannfjold" in folded or "population" in folded) and ("jan" in folded or "1." in folded or folded.endswith("1 january")):
                return str(code)
    return None


def _parts(result: dict) -> tuple[str, str, str]:
    stem = str(result.get("table_id") or "").split("#", 1)[0]
    if stem.endswith(".px"):
        stem = stem[:-3]
    titles: list[str] = []
    labels: list[str] = []
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    if source.get("title"):
        titles.append(str(source["title"]))
    cells = list(source.get("cells") or [])
    for claim in result.get("claims") or []:
        if isinstance(claim, dict):
            cells.extend(claim.get("cells") or [])
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        if not stem and cell.get("table_id"):
            stem = str(cell.get("table_id")).removesuffix(".px")
        if cell.get("title"):
            titles.append(str(cell["title"]))
        raw = cell.get("labels") or {}
        if isinstance(raw, dict):
            labels.extend(str(value) for value in raw.values())
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    labels.append(str(item.get("label") or ""))
    return stem, fold(" ".join(titles)), fold(" ".join(labels))


def blocks(question: str, result: dict) -> bool:
    """True when this stated cell is a different measure from the question."""
    if not enabled() or result.get("refused") or result.get("value") in (None, ""):
        return False
    if _two_asks(_text(question)):
        return False
    stem, title, labels = _parts(result)
    text = _text(question)
    if kang_missed_death(question) and stem in _POPULATION_TABLES and "dan" not in f"{title} {labels}" and "death" not in f"{title} {labels}":
        return True
    if foreign_citizens(question) and stem in _POPULATION_TABLES:
        return True
    if register_question(question) and stem in _POPULATION_TABLES and stem != "MAN00000":
        return True
    if basic_wage(question) and stem == "LAU04000":
        return True
    if unemployment_is_rate(text) and ("atvinnulausir" in labels or "estimated number" in labels or "aetladur fjoldi" in labels):
        if "%" not in labels and "hlutfall" not in labels and "rate" not in labels:
            return True
    if monthly_goods(question) and stem == "THJ01102":
        return True
    if enabled() and _goods(text) and not _commodity(text) and stem == "UTA06001":
        return True
    if enabled() and national_sex(question) and stem == "MAN02007":
        return True
    if generic_pupils(question) and (
        (stem.startswith("SKO") and stem != "SKO02101")
        or "fjoldi skola" in labels
        or "number of schools" in labels
    ):
        return True
    if enabled() and _asks_euro(text) and not _asks_dollar(text) and ("bandarikjadal" in labels or re.search(r"\busd\b", labels)):
        return True
    if enabled() and _exchange(text) and _year(question) and not _month(text):
        if _month(labels) and "allt arid" not in labels and "all year" not in labels:
            return True
    return False


def _lead(catalogue, hits: list[Hit], stem: str) -> list[Hit]:
    table = catalogue.by_id.get(stem + ".px") or catalogue.by_id.get(stem)
    if table is None:
        return hits
    kept = [hit for hit in hits if str(hit.table.id).removesuffix(".px") != stem]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead, *kept]


def apply_measure_guard(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    """Lead with the table whose measure the question named."""
    if not enabled() or _two_asks(_text(question)):
        return hits
    if register_question(question):
        return _lead(catalogue, hits, "MAN00000")
    if national_sex(question):
        return _lead(catalogue, hits, "MAN00101")
    if generic_pupils(question):
        return _lead(catalogue, hits, "SKO02101")
    if monthly_goods(question):
        return _lead(catalogue, hits, "UTA06002")
    return hits
