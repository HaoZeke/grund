"""Retrieval over the bilingual PxWeb catalogue.

Each catalogue path is one document. BM25 sees the title, the path, the
variable names, and every value label, in both languages, after
lemmatization. A second BM25 sees only the value labels. Embeddings cover
the heading (title, path, variable names). Label passages are optional.
The three rankings are fused with reciprocal rank fusion. A file name that
is published on more than one path keeps the higher score. Gold tables
are not an input.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import sys
import zlib
from collections import Counter
from pathlib import Path

import numpy as np

from grund_lang.fold import STOP, fold
from grund_lang.lemma import analyze, lemmatize_label
from grund_lang.types import Candidate
from grund_lang.values import bind_values

_RRF_K = 60
_CLAUSE = re.compile(
    r"\s+(?:and|og)\s+(?=(?:what|how|hve|hver|hvert|hvað|hvad)\b)",
    re.IGNORECASE,
)
_EMBED_MODEL = "intfloat/multilingual-e5-large"


def table_key(table_id: str) -> str:
    base = table_id.split("#", 1)[0]
    if base.endswith(".px"):
        base = base[:-3]
    return base


def _clauses(question: str) -> list[str]:
    parts = [part.strip() for part in _CLAUSE.split(question) if part.strip()]
    if len(parts) >= 2 and all(len(part) > 12 for part in parts):
        return [part if part.endswith("?") else part + "?" for part in parts]
    return [question]


class BM25:
    def __init__(self, docs: list[Counter[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.tf = docs
        self.n = len(docs)
        self.lengths = [sum(doc.values()) for doc in docs]
        self.avg = (sum(self.lengths) / self.n) if self.n else 0.0
        df: Counter[str] = Counter()
        for doc in docs:
            df.update(doc.keys())
        self.df = df

    def scores(self, query: list[str]) -> list[float]:
        totals = [0.0] * self.n
        if not self.n:
            return totals
        for term in set(query):
            document_frequency = self.df.get(term, 0)
            if not document_frequency:
                continue
            idf = math.log(1.0 + (self.n - document_frequency + 0.5) / (document_frequency + 0.5))
            for index, doc in enumerate(self.tf):
                frequency = doc.get(term, 0)
                if not frequency:
                    continue
                length_norm = 1 - self.b + self.b * self.lengths[index] / (self.avg or 1)
                totals[index] += idf * frequency * (self.k1 + 1) / (frequency + self.k1 * length_norm)
        return totals


def _chargram(text: str, dim: int = 384) -> np.ndarray:
    vector = np.zeros(dim, dtype=np.float32)
    padded = f" {text.lower()} "
    encoded = padded.encode("utf-8", errors="ignore")
    for size in (3, 4, 5):
        if len(encoded) < size:
            continue
        for start in range(len(encoded) - size + 1):
            digest = zlib.crc32(encoded[start : start + size])
            sign = 1.0 if digest & 1 else -1.0
            vector[digest % dim] += sign
    return vector


class Embedder:
    """Passage embeddings. The multilingual checkpoint is preferred.

    Queries and passages take the checkpoint's prefixes. If the weights are
    not available, a character n-gram vector is used and the manifest says so.
    """

    def __init__(self, kind: str = "auto") -> None:
        self.kind = "chargram"
        self.dim = 384
        self.model_name = "chargram-384"
        self.error: str | None = None
        self._model = None
        self._query_cache: dict[str, np.ndarray] = {}
        if kind == "chargram":
            return
        cache = os.environ.get("GRUND_EMBED_CACHE")
        try:
            from fastembed import TextEmbedding

            kwargs = {"cache_dir": cache} if cache else {}
            self._model = TextEmbedding(_EMBED_MODEL, **kwargs)
            self.kind = "e5"
            self.dim = 1024
            self.model_name = _EMBED_MODEL
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            if kind == "e5":
                raise

    def embed(self, texts: list[str], prefix: str) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        # A pair search embeds each half twice. The vector depends only on the text.
        if len(texts) == 1:
            key = prefix + texts[0]
            cached = self._query_cache.get(key)
            if cached is not None:
                return cached
        prefixed = [f"{prefix}{text}" for text in texts]
        if self._model is not None:
            rows = [np.asarray(vector, dtype=np.float32) for vector in self._model.embed(prefixed)]
            matrix = np.vstack(rows)
        else:
            matrix = np.vstack([_chargram(text, self.dim) for text in prefixed])
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix = (matrix / norms).astype(np.float32)
        if len(texts) == 1:
            if len(self._query_cache) > 64:
                self._query_cache.clear()
            self._query_cache[prefix + texts[0]] = matrix
        return matrix


def _accumulate(counter: Counter[str], text: str) -> None:
    for token in lemmatize_label(text):
        if token in STOP:
            continue
        if len(token) <= 2 and not (token.isdigit() and len(token) == 4):
            continue
        counter[token] += 1


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            kept.append(item)
    return kept


def passages_for(table, *, embed_labels: bool = False) -> list[str]:
    """Heading passage, and, when asked, every value label in both languages."""
    titles: list[str] = []
    names: list[str] = []
    labels: list[str] = []
    for edition in table.editions.values():
        titles.append(edition.title)
        titles.extend(getattr(edition, "path_texts", []) or [])
        for variable in edition.variables:
            names.append(variable.text)
            for code, label in variable.values:
                text = str(label or code or "").strip()
                if text:
                    labels.append(text)
    heading_bits = _unique(titles + names)
    heading = ". ".join(heading_bits)[:1400] or table_key(table.id)
    chunks = [heading]
    if not embed_labels:
        return chunks
    prefix = (titles[0] if titles else table_key(table.id))[:160]
    bucket: list[str] = []
    size = 0
    for label in _unique(labels):
        if size + len(label) > 600 and bucket:
            chunks.append(prefix + ": " + " | ".join(bucket))
            bucket = []
            size = 0
        bucket.append(label)
        size += len(label) + 3
    if bucket:
        chunks.append(prefix + ": " + " | ".join(bucket))
    return chunks


def _counters(table) -> tuple[Counter[str], Counter[str]]:
    title: Counter[str] = Counter()
    values: Counter[str] = Counter()
    for edition in table.editions.values():
        _accumulate(title, edition.title)
        _accumulate(title, getattr(edition, "db", "") or "")
        for piece in getattr(edition, "path_texts", []) or []:
            _accumulate(title, piece)
        for variable in edition.variables:
            _accumulate(title, variable.text)
            _accumulate(title, variable.code)
            for code, label in variable.values:
                _accumulate(values, str(label or ""))
                if code and not re.fullmatch(r"(?:19|20)\d{2}(?:[MQ]\d{1,2})?", str(code)):
                    _accumulate(values, str(code))
    return title, values


def _years(table) -> set[int]:
    found: set[int] = set()
    for edition in table.editions.values():
        years = getattr(edition, "years", None)
        if callable(years):
            found |= set(years())
    return found


def _unit_score(values: list[float]) -> list[float]:
    """Min-max scale. A flat vector stays zero so it does not invent a ranking."""
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high - low < 1e-9:
        return [0.0] * len(values)
    span = high - low
    return [(value - low) / span for value in values]


def _ranks(scores: list[float]) -> list[int]:
    order = sorted(range(len(scores)), key=lambda index: (-round(scores[index], 6), index))
    ranks = [0] * len(scores)
    for place, index in enumerate(order, start=1):
        ranks[index] = place
    return ranks


_OLDER = ("soguleg", "eldra", "eldri", "earlier", "previous")


def _content_tokens(text: str) -> set[str]:
    found = set()
    for token in re.findall(r"[a-z0-9]+", fold(text)):
        if token in STOP or len(token) <= 2:
            continue
        if len(token) == 4 and token.isdigit():
            continue
        found.add(token)
    return found


def _title_years(title: str) -> set[int]:
    """Years a title claims to cover, including a closed or open span.

    An index base such as 1988=100 is not a year the series is limited to.
    """
    cleaned = re.sub(r"(?:18|19|20)\d{2}\s*=\s*100", " ", title or "")
    cleaned = re.sub(r"(?:grunnur|grunn|base)\s+(?:19|20)\d{2}", " ", cleaned, flags=re.IGNORECASE)
    raw = [int(year) for year in re.findall(r"(?:18|19|20)\d{2}", cleaned)]
    if not raw:
        return set()
    if re.search(r"(?:18|19|20)\d{2}\s*[-–]\s*$", cleaned.strip()):
        return set(range(min(raw), 2101))
    if re.search(r"(?:frá|from)\s+(?:18|19|20)\d{2}\s*$", cleaned.strip(), re.IGNORECASE):
        return set(range(min(raw), 2101))
    if re.search(r"(?:18|19|20)\d{2}\s*[-–]\s*(?:18|19|20)\d{2}", cleaned):
        return set(range(min(raw), max(raw) + 1))
    return set(raw)


def _known_years(table, published: set[int]) -> set[int]:
    """Years the table can answer.

    A span printed on the title is the published coverage. Value codes are
    used only when the title does not state a span.
    """
    stated: set[int] = set()
    for edition in table.editions.values():
        stated |= _title_years(edition.title or "")
    return stated or set(published)


def _token_covered(token: str, question_terms: set[str]) -> bool:
    if token in question_terms:
        return True
    if len(token) > 3 and token.endswith("s") and token[:-1] in question_terms:
        return True
    if len(token) > 3 and (token + "s") in question_terms:
        return True
    return False


def _older_series(table) -> bool:
    parts: list[str] = []
    for edition in table.editions.values():
        parts.append(edition.db or "")
        parts.extend(edition.path or [])
        parts.extend(edition.path_texts or [])
    text = fold(" ".join(parts))
    return any(mark in text for mark in _OLDER)


def _asks_older(question: str) -> bool:
    text = fold(question)
    return any(mark in text for mark in _OLDER + ("historical",))


def _title_tokens(title: str) -> set[str]:
    return _content_tokens(re.sub(r"\b(?:19|20)\d{2}\b", " ", title or ""))


def _specific_title(tokens: set[str]) -> bool:
    """A one-word heading such as "Population" is not a series name.

    A real one-word series is a long compound. Two or more content words
    are always specific.
    """
    if len(tokens) >= 2:
        return True
    return bool(tokens) and max(len(token) for token in tokens) >= 12


def _title_covered(question: str, table) -> bool:
    """True when every content word of a specific title is already in the question.

    The year span is not part of that check.
    """
    question_terms = _content_tokens(question)
    for edition in table.editions.values():
        tokens = _title_tokens(edition.title or "")
        if not _specific_title(tokens):
            continue
        if tokens and all(_token_covered(token, question_terms) for token in tokens):
            return True
    return False


def _coverage_end(covered: set[int], published: set[int]) -> int | None:
    """Last year the table can answer, from the title span or the value codes."""
    pool = covered or published
    return max(pool) if pool else None


def _wants_old_period(question: str, asked: set[int]) -> bool:
    """The question names a historical series or a year in the last century."""
    if _asks_older(question):
        return True
    return any(year < 2000 for year in asked)


def _series_adjustment(question: str, table, asked: set[int], published: set[int], analysis=None) -> tuple[float, float]:
    """Prefer a continuing series, and a title the question already recites.

    Coverage comes from the title span and the year codes, not from the
    table id. A discontinued series, or a copy filed under an earlier
    heading, loses when the question does not ask for an old period. A
    one-word heading does not count as a recited title.
    """
    multiplier = 1.0
    covered = _known_years(table, published)
    inside = bool(asked and covered and asked <= covered)
    if asked and covered and not inside:
        multiplier *= 0.4
    historical = _older_series(table)
    wants_old = _wants_old_period(question, asked)
    recited = _title_covered(question, table)
    # A discontinued copy loses when the question did not ask for it.
    # A title the question recites is that series, even if the path says earlier.
    if historical and not wants_old and not recited:
        multiplier *= 0.5
    end = _coverage_end(covered, published)
    if not wants_old and end is not None and end < 2015 and not inside:
        multiplier *= 0.55
    bonus = 0.07 if recited else 0.0
    if analysis is not None and any(
        span.kind in {"month", "point"} and span.month for span in analysis.dates
    ):
        titles = fold(" ".join(edition.title or "" for edition in table.editions.values()))
        if any(word in titles for word in ("arsmedal", "annual average", "arleg medalt")):
            multiplier *= 0.65
        if any(word in titles for word in ("eftir manud", "by month", "manadar")):
            bonus += 0.03
    if analysis is not None and any(span.kind == "quarter" for span in analysis.dates):
        titles = fold(" ".join(edition.title or "" for edition in table.editions.values()))
        quarterly = any(word in titles for word in ("quarter", "arsfjord"))
        annual = any(word in titles for word in ("by year", "eftir arum", "arlega"))
        if annual and not quarterly:
            multiplier *= 0.7
        if quarterly:
            bonus += 0.03
    text = fold(question)
    if re.search(r"\b1\s*\.?\s*(?:january|januar)\b", text) or "arsbyrjun" in text:
        titles = fold(" ".join(edition.title or "" for edition in table.editions.values()))
        if any(word in titles for word in ("average population", "medalmannfjold")):
            multiplier *= 0.65
    bonus += _municipality_population(question, table, analysis)
    head_bonus, head_multiplier = _headline(question, table, analysis)
    bonus += head_bonus
    multiplier *= head_multiplier
    if _national_headcount(question):
        if _population_overview(table):
            bonus += 0.06
        elif _breakdown_table(table) and not _question_names_breakdown(question):
            multiplier *= 0.5
    # A count of one sex is the population table. Labour, constant prices,
    # and a quarterly GDP table are different series.
    from grund.agree_hyb import (
        constant_price_title,
        labour_title_for_headcount,
        quarterly_gdp_title,
        sex_headcount,
    )

    titles = fold(" ".join(edition.title or "" for edition in table.editions.values()))
    if (
        labour_title_for_headcount(titles, question)
        or quarterly_gdp_title(titles, question)
        or constant_price_title(titles, question)
    ):
        multiplier *= 0.35
    if sex_headcount(question) and ("thjodskra" in text or "a landinu" in text):
        if any(
            phrase in titles
            for phrase in (
                "mannfjoldi eftir kyni og aldri",
                "mannfjoldi eftir landshlut",
                "population by sex and age",
                "population by regions, sex",
            )
        ) and not any(word in titles for word in ("ofmat", "overestimation", "breytt adferd", "medalmannfjold")):
            bonus += 0.5
    return multiplier, bonus


_QUALIFIERS = (
    "sveitarfelag", "municipality", "municipalit",
    "faedingarland", "country of birth",
    "rikisfang", "citizenship",
    "per capita", "a mann", "per head",
    "percentage of", "hlutfall af",
    "visitolu", "indice", "indices",
    "manntal", "census",
    "hotelum", "guesthouse",
    "local government", "sveitarstjorn",
    "satellite", "forms of tourism", "tegund ferdamanna",
    "by municipalities", "eftir sveitarfelog",
    "indexation", "verdtrygging", "financial obligation",
    "foreldr", "parents",
    "1st", "fyrsta barn", "1. barn",
    "birth order", "faedingarrod", "hjuskap", "marital", "martial",
    "participation", "thattaka",
    "building stage", "byggingarstig",
    "per teacher", "a kennara",
    "heavy industry", "storidju",
    "aircraft", "flugumferd",
    "cause of", "orsok",
    "reykjav", "district", "hverfi",
    "landshlut", "byggdakj", "localit", "urban nucle",
    "thettbyl", "urbanis", "postcode", "postnumer",
)


def _mentions_catch(text: str) -> bool:
    """A catch question, not every word that happens to contain those letters."""
    if "catch" in text or "heildarafl" in text:
        return True
    return bool(re.search(r"(?<![a-z])afli(?![a-z])", text))


_PLACE_SUFFIXES = ("kaupstadur", "sveitarfelag", "hreppur", "byggd", "baer")


def _place_stem(label: str) -> str:
    folded = fold(label)
    for suffix in _PLACE_SUFFIXES:
        if folded.endswith(suffix) and len(folded) - len(suffix) >= 5:
            return folded[: -len(suffix)]
    return folded


def _municipality_population(question: str, table, analysis) -> float:
    """A named municipality is a value label, not a word in the table title.

    The population-by-municipality table is the headline for that place.
    A sunshine or catch table that happens to print the place name is not.
    """
    if analysis is None or "population" not in set(analysis.concepts):
        return 0.0
    titles = fold(" ".join(edition.title or "" for edition in table.editions.values()))
    if not any(word in titles for word in ("population", "mannfjold")):
        return 0.0
    if not any(word in titles for word in ("municip", "sveitarfelag")):
        return 0.0
    text = fold(question)
    for edition in table.editions.values():
        for variable in edition.variables:
            name = fold(variable.text or "")
            if "municip" not in name and "sveitarfelag" not in name:
                continue
            for _code, label in variable.values:
                stem = _place_stem(str(label or ""))
                if len(stem) < 6 or stem in {"total", "alls"}:
                    continue
                head = stem[:7]
                if stem in text or (len(head) >= 6 and head in text):
                    return 0.06
    return 0.0


def _headline(question: str, table, analysis) -> tuple[float, float]:
    """Boost a title that states the asked topic and does not add a split.

    Only a named subject counts: population, GDP, overnight stays, an exchange
    rate, or the place the question names. A qualifier the question did not
    use, such as "by municipality" or "index", cuts that boost.
    """
    if analysis is None:
        return 0.0, 1.0
    text = fold(question)
    markers: list[str] = []
    concepts = set(analysis.concepts)
    if "gdp" in concepts:
        markers += ["landsframleidsl", "gross domestic product"]
    if "exchange_rate" in concepts:
        markers += ["gengi", "exchange rate", "selling rate", "solugengi", "usd", "bandarikjad"]
    if "overnight_stays" in concepts or "accommodation" in concepts:
        markers += ["gistin", "overnight stay"]
    if "population" in concepts and (_national_headcount(question) or "reykjav" in text):
        markers += ["mannfjold", "population", "lykiltol"]
    if "cpi" in concepts:
        markers += ["consumer price", "neysluverd"]
    if "births" in concepts or any(word in text for word in ("faedd", "birth")):
        markers += ["faeding", "faeddir", "faedd", "birth"]
    if "deaths" in concepts:
        markers += ["death", "danir", "andlat"]
    if "unemployment" in concepts:
        markers += ["unemployment", "atvinnuleys"]
    if "immigrants" in concepts:
        markers += ["immigrant", "innflytjend", "by origin", "eftir bakgrunn"]
    if "citizenship_foreign" in concepts:
        markers += ["foreign citizen", "erlend rikisborg"]
    if "wage_index" in concepts and not any(word in text for word in ("basic", "grunnlaun")):
        markers += ["wage index", "launavisitala"]
    if any(word in text for word in ("building cost", "byggingarvisital", "byggingarkostnad")):
        markers += ["building cost", "byggingarvisital", "byggingarkostnad"]
    if any(word in text for word in ("residential property", "ibudaverd", "ibudarhusnaed")):
        markers += ["residential property", "ibudaverd"]
    if any(word in text for word in ("generat", "orkuvinnsl", "raforkuvinnsl")):
        markers += ["generat", "orkuvinnsl"]
    if any(word in text for word in ("passenger", "farthaeg", "farth")):
        markers += ["passenger", "farth"]
    if _mentions_catch(text):
        markers += ["catch", "heildarafl", "afli"]
    need_sex = "population" in concepts and bool({"sex_female", "sex_male"} & concepts)
    if need_sex:
        markers += ["mannfjold", "population"]
    place = "reykjav" in text
    if need_sex:
        titles = fold(" ".join(edition.title or "" for edition in table.editions.values()))
        if any(
            word in titles and word not in text
            for word in (
                "origin", "bakgrunn", "faeding", "country of birth",
                "postcode", "postnumer", "thettbyl", "landshlut", "byggdakj",
                "sveitarfelag", "municip", "region",
            )
        ):
            markers = [marker for marker in markers if marker not in {"mannfjold", "population", "lykiltol"}]
    if not markers and not place:
        return 0.0, 1.0
    matched = False
    qualified = False
    for edition in table.editions.values():
        title = fold(edition.title or "")
        subject = any(marker in title for marker in markers) if markers else False
        if place and "population" in concepts and not need_sex:
            subject = subject and "reykjav" in title
        if need_sex and not any(word in title for word in ("sex", "kyn")):
            subject = False
        if not subject:
            continue
        if not _specific_title(_title_tokens(edition.title or "")):
            continue
        matched = True
        if any(marker in title and marker not in text for marker in _QUALIFIERS):
            qualified = True
    if not matched:
        return 0.0, 1.0
    if qualified and "reykjav" not in text:
        return 0.0, 0.72
    bonus = 0.04 if qualified else 0.06
    if _plain_aggregate(table, markers) and not any(word in text for word in ("index", "visit", "percent", "hlutfall", "capita")):
        bonus += 0.03
    return bonus, 1.0


def _plain_aggregate(table, markers: list[str]) -> bool:
    """A value label that is the topic itself, not an index, a share, or a per-capita line."""
    blocked = ("index", "visit", "volume", "percent", "hlutfall", "capita", "a mann", "breyt", "growth")
    for edition in table.editions.values():
        for variable in edition.variables:
            if variable.time:
                continue
            for _code, label in variable.values:
                folded = fold(str(label or ""))
                if not any(marker in folded for marker in markers):
                    continue
                if any(word in folded for word in blocked):
                    continue
                return True
    return False


def _national_headcount(question: str) -> bool:
    """A question for the number of people in Iceland, not a rate or a subgroup."""
    text = fold(question)
    tokens = set(re.findall(r"[a-z0-9]+", text))
    people = bool(tokens & {
        "population", "mannfjoldi", "mannfjoldinn", "people", "bjuggu", "bua",
        "inhabitant", "inhabitants", "ibui",
    }) or "mannfjold" in text
    place = bool(tokens & {"island", "islandi", "iceland"}) or "mannfjold" in text
    if not (people and place):
        return False
    if any(word in text for word in ("percent", "hlutfall", "ratio", "per inhabitant", "a hvern", "prosent")):
        return False
    if _question_names_breakdown(question):
        return False
    if any(word in tokens for word in ("konur", "karlar", "kona", "karl", "women", "woman", "men", "males", "females")):
        return False
    return True


def _question_names_breakdown(question: str) -> bool:
    text = fold(question)
    tokens = set(re.findall(r"[a-z0-9]+", text))
    if tokens & {"reykjavik", "reykjavikur", "born"} or "hofudborg" in text or "faed" in text:
        return True
    for words in _BREAKDOWNS:
        if any(word in text for word in words):
            return True
    return False


def _breakdown_table(table) -> bool:
    blob = _blob(table)
    return any(any(word in blob for word in words) for words in _BREAKDOWNS)


def _population_overview(table) -> bool:
    """Key figures or the sex-and-age overview, not a ratio and not a subgroup split."""
    if _breakdown_table(table):
        return False
    for edition in table.editions.values():
        title = edition.title or ""
        if not _specific_title(_title_tokens(title)):
            continue
        folded = fold(title)
        path = fold(" ".join(edition.path_texts or []))
        if any(word in folded for word in ("hlutfall", "ratio", "percent", "prosent")):
            continue
        people = "mannfjold" in folded or "population" in folded
        overview = "yfirlit" in path or "overview" in path or "lykiltol" in folded
        if people and overview:
            return True
    return False


_MEASURE = ("prosent", "percent", "hlutfall", "percentage", "visital", "index", "fjoldi", "number", "count")
# A national population question names Iceland as the place people live.
# These breakdowns are a different question unless the wording asks for them.
_BREAKDOWNS = (
    ("faeding", "faedingarland", "country of birth", "born in"),
    ("rikisfang", "rikisborg", "citizenship", "citizen"),
    ("sveitarfelag", "municipality"),
    ("bakgrunn", "origin"),
    ("ofmat", "overestimation", "breytt adferd", "change of method"),
)
_TABLE_TERMS: dict[str, set[str]] = {}


def _table_terms(table) -> set[str]:
    """Lemmas of the title, the variable names, and measure-like value labels.

    Every municipality name is not a retrieval term. A label that says
    percent, index, or count is, because that is how the table is measured.
    """
    key = getattr(table, "id", None) or id(table)
    cached = _TABLE_TERMS.get(key)
    if cached is not None:
        return cached
    terms: set[str] = set()
    for edition in table.editions.values():
        terms.update(lemmatize_label(edition.title or ""))
        for variable in edition.variables:
            terms.update(lemmatize_label(variable.text or ""))
            for _code, label in variable.values:
                folded = fold(str(label or ""))
                if any(mark in folded for mark in _MEASURE):
                    terms.update(lemmatize_label(str(label)))
    _TABLE_TERMS[key] = terms
    return terms


def _blob(table) -> str:
    parts = []
    for edition in table.editions.values():
        parts.append(edition.title or "")
        parts.extend(edition.path_texts or [])
        for variable in edition.variables:
            parts.append(variable.text or "")
            parts.append(variable.code or "")
    return fold(" ".join(parts))


def _asks_words(question: str, analysis, words: tuple[str, ...]) -> bool:
    text = fold(question)
    terms = " ".join(analysis.terms)
    concepts = " ".join(analysis.concepts)
    blob = f"{text} {terms} {concepts}"
    if any(word in blob for word in words):
        return True
    if "sveitarfelag" in words or "municipality" in words:
        return "capital_region" in analysis.concepts or "reykjavik" in text
    return False


def _title_blob(table) -> str:
    """Title and variable names, without the subject folder.

    The folder Bakgrunnur holds the plain citizenship series as well as
    the origin split. The folder name is not itself a breakdown.
    """
    parts = []
    for edition in table.editions.values():
        parts.append(edition.title or "")
        for variable in edition.variables:
            parts.append(variable.text or "")
    return fold(" ".join(parts))


def _unasked_breakdown(question: str, analysis, table) -> bool:
    """The table is a birth, citizenship, municipality, or adjustment split nobody asked for."""
    if table is None:
        return False
    blob = _title_blob(table)
    for words in _BREAKDOWNS:
        if any(word in blob for word in words) and not _asks_words(question, analysis, words):
            return True
    return False


def _plain_title(table) -> str:
    titles = []
    for edition in table.editions.values():
        title = re.sub(r"\b(?:19|20)\d{2}\b", " ", edition.title or "")
        titles.append(fold(title))
    return " ".join(sorted(set(titles)))


def _rerank(question: str, candidates: list, analysis, tables: dict) -> list:
    """Keep the fused order, with two swaps.

    A breakdown the question did not ask for (country of birth, citizenship,
    municipality, origin, a method-change adjustment) loses to the first
    overview table already in the list. A historical copy with the same title
    loses to the current series. Nothing else moves, so a list that was
    already right stays right.
    """
    if len(candidates) < 2:
        return candidates
    wants_old = _wants_old_period(question, _asked_years(analysis))

    def features(candidate):
        table = tables.get(candidate.table_id)
        breakdown = _unasked_breakdown(question, analysis, table)
        historical = bool(table is not None and _older_series(table) and not wants_old)
        title = _plain_title(table) if table is not None else ""
        return breakdown, historical, title

    feats = [features(candidate) for candidate in candidates]
    choice = 0
    for index, feat in enumerate(feats):
        if feats[choice][0] and not feat[0]:
            choice = index
            break
    if choice == 0 and feats[0][1]:
        for index, feat in enumerate(feats):
            if feat[1] or not feat[2] or feat[2] != feats[0][2]:
                continue
            choice = index
            break
    if choice == 0:
        return candidates
    picked = candidates[choice]
    return [picked] + [candidate for index, candidate in enumerate(candidates) if index != choice]


def load_tables(index_dir: Path) -> list:
    from grund_index.catalogue import edition_from_json
    from grund_index.model import Table

    index_dir = Path(index_dir)
    path = index_dir / "tables.jsonl.gz"
    if not path.exists():
        path = index_dir / "tables.jsonl"
    grouped: dict[str, Table] = {}
    order: list[str] = []
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            table = grouped.get(payload["id"])
            if table is None:
                table = Table(id=payload["id"])
                grouped[payload["id"]] = table
                order.append(payload["id"])
            edition = edition_from_json(payload)
            table.editions[edition.lang] = edition
    return [grouped[table_id] for table_id in order]


def load_catalogue(catalogue: Path, metadata: Path | None = None) -> list:
    """One document per catalogue path, with value labels joined on the table id.

    The catalogue is the list of every published table in both languages.
    The metadata index, when it is present, supplies variable names and
    value labels for the same ids. A file name that is published on two
    paths stays two documents; search keeps the higher score for that id.
    """
    from grund_index.model import Edition, Table

    meta: dict = {}
    if metadata is not None and Path(metadata).exists():
        for table in load_tables(metadata):
            meta[table_key(table.id)] = table
    tables = []
    with Path(catalogue).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            table_id = str(row.get("id") or "")
            if not table_id:
                continue
            table = Table(id=f"{table_id}.px#{number}")
            source = meta.get(table_id)
            for lang in ("is", "en"):
                block = row.get(lang)
                if not isinstance(block, dict) or not block.get("title"):
                    continue
                variables = []
                if source is not None and lang in source.editions:
                    variables = source.editions[lang].variables
                table.editions[lang] = Edition(
                    lang=lang,
                    title=block.get("title") or "",
                    db=str(row.get("subject") or ""),
                    path=list(block.get("path_ids") or row.get("path_ids") or []),
                    path_texts=list(block.get("path_texts") or []),
                    url=block.get("url") or "",
                    updated=block.get("updated"),
                    variables=variables,
                )
            if table.editions:
                tables.append(table)
    return tables


class RetrievalIndex:
    def __init__(
        self,
        tables: list,
        title_docs: list[Counter[str]],
        value_docs: list[Counter[str]],
        embedder: Embedder,
        matrix: np.ndarray | None,
        owners: np.ndarray | None,
    ) -> None:
        self.tables = tables
        self.by_key = {table_key(table.id): table for table in tables}
        self.title_bm25 = BM25(title_docs)
        self.value_bm25 = BM25(value_docs)
        self.embedder = embedder
        self.matrix = matrix
        self.owners = owners
        self.years = [_years(table) for table in tables]
        self.public_ids = [table_key(table.id) for table in tables]
        self.fusion = os.environ.get("GRUND_FUSION", "rrf").strip() or "rrf"
        self.label_matrix: np.ndarray | None = None
        self.label_owners: np.ndarray | None = None

    def search(self, question: str, k: int = 10, context: str | None = None) -> list[Candidate]:
        from grund_lang.followup import with_context

        question = with_context(context, question)
        parts = _clauses(question)
        if len(parts) == 1:
            return self._search_one(question, k)
        # A comparison names two series. The first series leads the list.
        # Score-only fusion put whichever half matched more strongly first,
        # so the first gold table missed top-1 even when both were retrieved.
        halves = [self._search_one(part, k, bind=False) for part in parts]
        ranked: list[Candidate] = []
        seen: set[str] = set()
        for half in halves:
            if half and half[0].table_id not in seen:
                seen.add(half[0].table_id)
                ranked.append(half[0])
        rest = sorted(
            (candidate for half in halves for candidate in half[1:]),
            key=lambda candidate: candidate.score,
            reverse=True,
        )
        for candidate in rest:
            if candidate.table_id in seen:
                continue
            seen.add(candidate.table_id)
            ranked.append(candidate)
            if len(ranked) >= k:
                break
        ranked = ranked[:k]
        full = analyze(question)
        for candidate in ranked:
            table = self.by_key[candidate.table_id]
            candidate.bindings = bind_values(question, _edition(table, full.language), full)
        return ranked

    def _search_one(self, question: str, k: int, bind: bool = True) -> list[Candidate]:
        if not self.tables:
            return []
        analysis = analyze(question)
        query = [term for term in analysis.terms if term not in STOP]
        title_scores = self.title_bm25.scores(query)
        value_scores = self.value_bm25.scores(query)
        cosine = self._cosine(question)
        label_cosine = [0.0] * len(self.tables)
        if os.environ.get("GRUND_LABEL_DENSE", "0") != "0":
            query_vector = self.embedder.embed([question], prefix="query: ")[0]
            label_cosine = self._dot(query_vector, self.label_matrix, self.label_owners)
        title_ranks = _ranks(title_scores)
        value_ranks = _ranks(value_scores)
        cosine_ranks = _ranks(cosine)
        label_ranks = _ranks(label_cosine) if any(label_cosine) else None
        asked = _asked_years(analysis)
        mode = os.environ.get("GRUND_FUSION", getattr(self, "fusion", "rrf") or "rrf").strip() or "rrf"
        weighted_parts: list[list[float]] = []
        if mode == "weighted":
            weighted_parts = [_unit_score(title_scores), _unit_score(value_scores)]
            if any(cosine):
                weighted_parts.append(_unit_score(cosine))
        fused: list[float] = []
        for index in range(len(self.tables)):
            if mode == "off":
                score = 1.0 / (_RRF_K + title_ranks[index]) + 1.0 / (_RRF_K + value_ranks[index])
            elif mode == "weighted":
                score = sum(part[index] for part in weighted_parts) / len(weighted_parts)
            else:
                score = (
                    1.0 / (_RRF_K + title_ranks[index])
                    + 1.0 / (_RRF_K + value_ranks[index])
                    + 1.0 / (_RRF_K + cosine_ranks[index])
                )
            # A label matrix is a second dense vote, and only when asked for.
            # Half a vote, so a table already at rank 1 is not pushed aside.
            if label_ranks is not None:
                score += 0.5 / (_RRF_K + label_ranks[index])
            multiplier, bonus = _series_adjustment(
                question, self.tables[index], asked, self.years[index], analysis
            )
            # A discontinued series must not keep a full topic bonus.
            # In-range tables have multiplier 1, so their score is unchanged.
            score = (score + bonus) * multiplier
            fused.append(score)
        order = sorted(
            range(len(self.tables)),
            key=lambda index: (-round(fused[index], 6), self.public_ids[index]),
        )
        found: list[Candidate] = []
        chosen: dict[str, object] = {}
        seen: set[str] = set()
        for index in order:
            public = self.public_ids[index]
            if public in seen:
                continue
            seen.add(public)
            if len(found) >= k:
                break
            table = self.tables[index]
            edition = _edition(table, analysis.language)
            bindings = bind_values(question, edition, analysis) if bind else []
            chosen[public] = table
            found.append(
                Candidate(
                    table_id=table_key(table.id),
                    score=fused[index],
                    bm25=title_scores[index],
                    cosine=cosine[index],
                    bindings=bindings,
                    bm25_rank=title_ranks[index],
                    cosine_rank=cosine_ranks[index],
                    value_bm25=value_scores[index],
                )
            )
        ranked = _rerank(question, found, analysis, chosen)
        ranked = self._apply_recall(question, ranked, analysis, k, bind)
        if os.environ.get("GRUND_IS_KANG_PLACES", "0") == "1":
            from grund_lang.kang_places import prefer_municipality

            ranked = prefer_municipality(ranked, analysis, self)
        return ranked

    def _apply_recall(self, question: str, ranked: list[Candidate], analysis, k: int, bind: bool) -> list[Candidate]:
        """Fill slots after the ranker prefix. Weak mode may replace rank 1."""
        from grund_lang.recall_small import channel, mix_ids

        mode = os.environ.get("GRUND_RECALL", "fill").strip().lower()
        # ``fill`` appends dense misses after the ranker list. ``weak`` may
        # replace rank 1 and stays off unless it is set. ``0`` loads nothing.
        if mode in {"0", "off", "false", "no"} or not ranked:
            return ranked
        if mode not in {"fill", "weak"}:
            return ranked
        recall = channel()
        if recall is None:
            return ranked
        raw_protect = os.environ.get("GRUND_RECALL_PROTECT", "").strip()
        extend = raw_protect == ""
        if extend:
            protect = max(k, 1)
        else:
            try:
                protect = max(1, int(raw_protect))
            except ValueError:
                protect = max(k, 1)
                extend = True
        dense = recall.top(question, max(k, 20))
        dense_ids = [table_id for table_id, _score in dense if table_id in self.by_key]
        dense_score = {table_id: score for table_id, score in dense}
        original = [candidate.table_id for candidate in ranked]
        lexical_ids = list(original)
        replaced = False
        if mode == "weak" and dense_ids and self._leader_is_weak(ranked, analysis):
            leader = dense_ids[0]
            if leader != lexical_ids[0]:
                lexical_ids = [leader] + [table_id for table_id in lexical_ids if table_id != leader]
                replaced = True
                protect = max(protect, 1)
        mixed = mix_ids(lexical_ids, dense_ids, k, protect, extend=extend and not replaced)
        if mixed == original[:k]:
            return ranked
        by_id = {candidate.table_id: candidate for candidate in ranked}
        leader_score = ranked[0].score
        ordered: list[Candidate] = []
        for table_id in mixed:
            existing = by_id.get(table_id)
            if existing is None:
                existing = self._candidate_from_public(
                    table_id, question, analysis, bind, cosine=dense_score.get(table_id, 0.0)
                )
                if existing is None:
                    continue
            ordered.append(existing)
        if not ordered:
            return ranked
        seen = {candidate.table_id for candidate in ranked}
        if replaced:
            ordered[0].score = leader_score + 1e-3
        floor = min(candidate.score for candidate in ranked)
        step = 1
        for candidate in ordered:
            if replaced and candidate is ordered[0]:
                continue
            if candidate.table_id in seen:
                continue
            candidate.score = floor - step * 1e-4
            step += 1
        return ordered

    def _leader_is_weak(self, ranked: list[Candidate], analysis) -> bool:
        if len(ranked) < 2 or ranked[0].score <= 0:
            margin = 0.0
        else:
            margin = (ranked[0].score - ranked[1].score) / ranked[0].score
        try:
            limit = float(os.environ.get("GRUND_RECALL_MARGIN", "0.05"))
        except ValueError:
            limit = 0.05
        if margin < limit:
            return True
        return not self._title_overlap(ranked[0].table_id, analysis)

    def _title_overlap(self, table_id: str, analysis) -> bool:
        terms = _content_lemmas(analysis)
        if not terms:
            return False
        return bool(terms & self._table_terms(table_id))

    def _table_terms(self, table_id: str) -> set[str]:
        cached = getattr(self, "_terms_by_public", None)
        if cached is None:
            cached = {}
            for index, public in enumerate(self.public_ids):
                bucket = cached.get(public)
                if bucket is None:
                    bucket = set()
                    cached[public] = bucket
                bucket.update(self.title_bm25.tf[index])
                bucket.update(self.value_bm25.tf[index])
            self._terms_by_public = cached
        return cached.get(table_id, set())

    def _candidate_from_public(
        self, table_id: str, question: str, analysis, bind: bool, cosine: float
    ) -> Candidate | None:
        table = self.by_key.get(table_id)
        if table is None:
            return None
        row = self._row_for(table_id)
        title_score = 0.0
        value_score = 0.0
        if row is not None:
            terms = _content_lemmas(analysis)
            title_score = float(sum(self.title_bm25.tf[row].get(term, 0) for term in terms))
            value_score = float(sum(self.value_bm25.tf[row].get(term, 0) for term in terms))
        edition = _edition(table, analysis.language)
        bindings = bind_values(question, edition, analysis) if bind else []
        return Candidate(
            table_id=table_id,
            score=0.0,
            bm25=title_score,
            cosine=cosine,
            bindings=bindings,
            value_bm25=value_score,
        )

    def _row_for(self, table_id: str) -> int | None:
        cached = getattr(self, "_row_by_public", None)
        if cached is None:
            cached = {}
            for index, public in enumerate(self.public_ids):
                cached.setdefault(public, index)
            self._row_by_public = cached
        return cached.get(table_id)

    def _cosine(self, question: str) -> list[float]:
        totals = [0.0] * len(self.tables)
        if self.matrix is None or self.owners is None or len(self.matrix) == 0:
            return totals
        query = self.embedder.embed([question], prefix="query: ")[0]
        return self._dot(query, self.matrix, self.owners)

    def _dot(self, query: np.ndarray, matrix: np.ndarray | None, owners: np.ndarray | None) -> list[float]:
        totals = [0.0] * len(self.tables)
        if matrix is None or owners is None or len(matrix) == 0:
            return totals
        if query.shape[0] != matrix.shape[1]:
            return totals
        scores = matrix @ query
        for index, owner in enumerate(owners):
            value = float(scores[index])
            if value > totals[int(owner)]:
                totals[int(owner)] = value
        return totals


def _content_lemmas(analysis) -> set[str]:
    """Question lemmas that can overlap a title or a value label."""
    return {
        term
        for term in analysis.terms
        if term not in STOP and len(term) >= 3 and not term.isdigit()
    }


def _edition(table, language: str):
    editions = table.editions
    if language in editions:
        return editions[language]
    if "en" in editions:
        return editions["en"]
    return next(iter(editions.values()))


def _asked_years(analysis) -> set[int]:
    years: set[int] = set()
    for span in analysis.dates:
        if span.kind == "annual_average" and span.year is None:
            continue
        if span.year:
            years.add(span.year)
        if span.end_year:
            years.add(span.end_year)
    for base in analysis.bases:
        years.discard(base)
    return years


def _embed_passages(embedder: Embedder, texts: list[str]) -> np.ndarray:
    if embedder.kind != "e5":
        return embedder.embed(texts, prefix="passage: ")
    batch = 48
    blocks = []
    for start in range(0, len(texts), batch):
        blocks.append(embedder.embed(texts[start : start + batch], prefix="passage: "))
        done = min(start + batch, len(texts))
        if done == len(texts) or done % 480 == 0:
            print(f"embedded {done}/{len(texts)}", file=sys.stderr)
    return np.vstack(blocks) if blocks else np.zeros((0, embedder.dim), dtype=np.float32)


def build_index(tables: list, *, embed: str = "auto", embed_labels: bool = False) -> RetrievalIndex:
    title_docs: list[Counter[str]] = []
    value_docs: list[Counter[str]] = []
    passages: list[str] = []
    owners: list[int] = []
    for index, table in enumerate(tables):
        title, values = _counters(table)
        title_docs.append(title)
        value_docs.append(values)
        for passage in passages_for(table, embed_labels=embed_labels):
            passages.append(passage)
            owners.append(index)
        if (index + 1) % 400 == 0:
            print(f"read {index + 1}/{len(tables)} tables, {len(passages)} passages", file=sys.stderr)
    print(f"passages {len(passages)}", file=sys.stderr)
    embedder = Embedder(kind="chargram" if embed == "chargram" else "auto")
    if embed == "e5" and embedder.kind != "e5":
        raise RuntimeError(embedder.error or "embedding checkpoint was not loaded")
    matrix = _embed_passages(embedder, passages)
    index = RetrievalIndex(tables, title_docs, value_docs, embedder, matrix, np.asarray(owners, dtype=np.int32))
    from grund_lang.rewrite import install_from_tables

    install_from_tables(tables)
    return index


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not Path(path).exists():
        return None
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def index_is_cached(out: Path, catalogue: Path | None, embed_labels: bool) -> dict | None:
    """Manifest of a finished build when the catalogue bytes and the matrix are unchanged."""
    manifest_path = Path(out) / "manifest.json"
    matrix_path = Path(out) / "embeddings.npy"
    if catalogue is None or not manifest_path.exists() or not matrix_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if manifest.get("catalogue_sha256") != _file_sha256(catalogue):
        return None
    if bool(manifest.get("embed_labels")) != bool(embed_labels):
        return None
    if manifest.get("embedding_kind") not in {"e5", "chargram"}:
        return None
    return manifest


def save_bm25(index: RetrievalIndex, out: Path) -> None:
    """Write the title and value postings so a later load does not re-lemmatize."""
    payload = [
        {"t": dict(title), "v": dict(values)}
        for title, values in zip(index.title_bm25.tf, index.value_bm25.tf)
    ]
    path = Path(out) / "bm25.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def load_bm25(path: Path, documents: int) -> tuple[list[Counter[str]], list[Counter[str]]] | None:
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list) or len(payload) != documents:
        return None
    titles = [Counter(item.get("t") or {}) for item in payload]
    values = [Counter(item.get("v") or {}) for item in payload]
    return titles, values


def _stored_path(out: Path, value: str | None) -> Path | None:
    """Resolve a manifest path. A relative path is inside the index directory."""
    if not value:
        return None
    candidate = Path(value)
    bundled = out / value
    if bundled.exists():
        return bundled
    if candidate.exists():
        return candidate
    named = out / candidate.name
    if named.exists():
        return named
    return candidate


def save_index(
    index: RetrievalIndex,
    out: Path,
    source: Path,
    *,
    catalogue: Path | None = None,
    metadata: Path | None = None,
    embed_labels: bool = False,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "embeddings.npy", index.matrix)
    np.save(out / "owners.npy", index.owners)
    manifest = {
        "source": str(source),
        "catalogue": str(catalogue) if catalogue else None,
        "metadata": str(metadata) if metadata else None,
        "embed_labels": embed_labels,
        "documents": len(index.tables),
        "tables": len(set(index.public_ids)),
        "passages": int(index.matrix.shape[0]) if index.matrix is not None else 0,
        "embedding_kind": index.embedder.kind,
        "embedding_model": index.embedder.model_name,
        "embedding_dim": index.embedder.dim,
        "embedding_error": index.embedder.error,
        "fusion": "rrf",
        "rrf_k": _RRF_K,
        "catalogue_sha256": _file_sha256(catalogue) if catalogue else None,
    }
    save_bm25(index, out)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_index(out: Path, *, source: Path | None = None) -> RetrievalIndex:
    """Load a saved embedding matrix. BM25 is read from disk when it was packed."""
    out = Path(out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    catalogue = _stored_path(out, manifest.get("catalogue"))
    if catalogue and catalogue.exists():
        metadata = _stored_path(out, manifest.get("metadata"))
        tables = load_catalogue(catalogue, metadata if metadata and metadata.exists() else None)
    else:
        source = source or _stored_path(out, manifest.get("source"))
        tables = load_tables(source)
    stored = load_bm25(out / "bm25.json.gz", len(tables))
    if stored is None:
        title_docs = []
        value_docs = []
        for index, table in enumerate(tables):
            title, values = _counters(table)
            title_docs.append(title)
            value_docs.append(values)
            if (index + 1) % 400 == 0:
                print(f"indexed {index + 1}/{len(tables)}", file=sys.stderr)
    else:
        title_docs, value_docs = stored
    matrix = np.load(out / "embeddings.npy")
    owners = np.load(out / "owners.npy")
    kind = manifest.get("embedding_kind", "chargram")
    embedder = Embedder(kind="chargram" if kind == "chargram" else "auto")
    if kind == "e5" and embedder.kind != "e5":
        matrix = None
        owners = None
    elif matrix.ndim != 2 or matrix.shape[1] != embedder.dim:
        matrix = None
        owners = None
    index = RetrievalIndex(tables, title_docs, value_docs, embedder, matrix, owners)
    from grund_lang.rewrite import install_from_tables

    install_from_tables(tables, cache=out / "rewrites.json")
    from grund_lang.lexicon import build as build_lexicon

    build_lexicon(tables)
    label_matrix = out / "label_embeddings.npy"
    label_owners = out / "label_owners.npy"
    if label_matrix.exists() and label_owners.exists() and index.matrix is not None:
        loaded = np.load(label_matrix)
        if loaded.ndim == 2 and loaded.shape[1] == index.matrix.shape[1] and len(loaded) == len(index.tables):
            index.label_matrix = loaded
            index.label_owners = np.load(label_owners)
    return index
