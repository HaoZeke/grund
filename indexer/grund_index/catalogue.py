"""Hybrid search over the bilingual table catalogue.

Score = 0.45 BM25 + 0.35 embedding cosine + 0.20 value-label overlap.
Embeddings are optional. Value overlap is what makes "females" or
"Reykjavík" select a column inside a table whose title never says so.
"""

from __future__ import annotations

import gzip
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from grund_index.embed import Embedder
from grund_index.model import Edition, Table, Variable
from grund_index.textutil import MONTH_NAMES, SYNONYMS, fold, inflections, lemmas, near_token, tokens

_TIME_CODE = re.compile(r"^(?:19|20)\d{2}(?:[mq]\d{1,2})?$", re.IGNORECASE)


@dataclass
class Hit:
    table: Table
    score: float
    bm25: float
    cosine: float
    value_boost: float


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs = docs
        self.n = len(docs)
        self.tf = [Counter(doc) for doc in docs]
        self.lengths = [len(doc) for doc in docs]
        self.avg = (sum(self.lengths) / self.n) if self.n else 0.0
        df: Counter[str] = Counter()
        for counted in self.tf:
            df.update(counted.keys())
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
            for index, counted in enumerate(self.tf):
                frequency = counted.get(term, 0)
                if not frequency:
                    continue
                length_norm = 1 - self.b + self.b * self.lengths[index] / (self.avg or 1)
                totals[index] += idf * frequency * (self.k1 + 1) / (frequency + self.k1 * length_norm)
        return totals


# Words that name the arithmetic, not the subject. They must not count as
# evidence that a title is about the question.
_OPERATION_QUERY = {
    "percentage", "percent", "proportion", "share", "hlutfall", "hlutdeild",
}


def _stem(token: str) -> str:
    for suffix in ("inum", "unum", "anna", "um", "ar", "ir", "ur", "inn", "an", "i", "a"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 5:
            return token[: -len(suffix)]
    if len(token) >= 10 and token.endswith("n") and token[-2] in "aeiou":
        return token[:-1]
    return token


def _matches(token: str, pool: set[str]) -> bool:
    """True when token is in the pool, including a plural or an Icelandic case ending."""
    if token in pool:
        return True
    if len(token) > 4 and token.endswith("s") and token[:-1] in pool:
        return True
    if len(token) > 4 and (token + "s") in pool:
        return True
    stem = _stem(token)
    if len(stem) < 6:
        return False
    for other in pool:
        other_stem = _stem(other)
        if len(other_stem) < 6:
            continue
        if stem == other_stem or other.startswith(stem) or stem.startswith(other_stem):
            return True
    return False


def _subject_bonus(question: str, title: str) -> float:
    """Separate tables that share a subject phrase from tables that only share a word.

    "Annual averages" occurs on both the CPI and the wage index. The consumer-price
    phrase is what keeps the wage index from answering a CPI question.
    """
    question_folded = fold(question)
    title_folded = fold(title)
    bonus = 0.0
    if "annual average" in question_folded or "arsmedal" in question_folded:
        if "annual average" in title_folded or "arsmedal" in title_folded:
            bonus += 0.35
        else:
            bonus -= 0.15
    wants_cpi = (
        "consumer price" in question_folded
        or "neysluverd" in question_folded
        or re.search(r"\b(cpi|vnv)\b", question_folded) is not None
    )
    if wants_cpi:
        has_cpi = (
            "consumer price" in title_folded
            or "neysluverd" in title_folded
            or re.search(r"\bcpi\b", title_folded) is not None
        )
        bonus += 0.30 if has_cpi else -0.20
    wants_internal = any(
        word in question_folded.split()
        for word in ("moved", "moves", "move", "migrated", "migration", "flutning", "internally", "internal", "fluttu", "buferlum", "innanlands")
    )
    if wants_internal and any(
        word in question_folded.split() for word in ("within", "internally", "internal", "innanlands", "buferlum")
    ):
        if "internal migration" in title_folded or "buferlafl" in title_folded:
            bonus += 0.25
        elif "population" in title_folded and "migration" not in title_folded:
            bonus -= 0.20
    names_a_place = any(
        word in question_folded
        for word in ("municipality", "sveitarfelag", "region", "landshluti", "localit", "byggdakjarn")
    )
    if wants_internal and not names_a_place:
        if any(word in title_folded for word in ("municipality", "sveitarfelag", "between regions", "localit", "milli landsvaed")):
            bonus -= 0.15
        if "internal migration" in title_folded or "buferlaflinnanland" in title_folded or "innanlands" in title_folded:
            bonus += 0.10
    wants_headline_change = any(
        phrase in question_folded
        for phrase in ("annual change", "arleg breyting", "arsbreyting", "yearly change")
    )
    if wants_headline_change:
        headline = ("breyting" in title_folded or "change" in title_folded) and (
            "neysluverd" in title_folded or "consumer price" in title_folded
        )
        if headline:
            bonus += 0.35
        if any(phrase in title_folded for phrase in ("fastskatt", "arsmedal", "ahrif", "constant tax", "annual average")):
            bonus -= 0.25
    return bonus


def _title_alignment(question: str, title: str) -> float:
    """How much of the question's subject the title actually covers.

    Synonyms count as a hit (women → females) but unmatched synonyms do not
    inflate the denominator. Extra title words that the question never used
    ("lifelong", "learning") pull the score down, so a longer off-topic title
    does not beat "Population by sex and age".
    """
    raw = [
        tok for tok in tokens(question, expand=False)
        if not tok.isdigit() and tok not in _OPERATION_QUERY
    ]
    if not raw:
        return _subject_bonus(question, title)
    title_set = set(tokens(title))
    expanded: set[str] = set()
    hits = 0
    for tok in raw:
        forms = [tok, *inflections(tok)]
        alts = set(forms)
        for form in forms:
            alts.update(SYNONYMS.get(form, []))
        expanded |= alts
        if any(_matches(alt, title_set) for alt in alts):
            hits += 1
    coverage = hits / len(raw)
    extras = []
    for tok in title_set:
        if tok.isdigit() or len(tok) <= 3:
            continue
        if any(_matches(tok, {alt}) for alt in expanded):
            continue
        extras.append(tok)
    return 0.45 * coverage - 0.035 * min(len(extras), 8) + _subject_bonus(question, title) + _exact_title_bonus(question, title)


def _exact_title_bonus(question: str, title: str) -> float:
    """Reward a title that the question already quotes, once years are ignored.

    "Population by sex and age" is in the question. "Population by origin, sex
    and age" is not, even though it shares three words.
    """
    question_folded = fold(question)
    title_folded = fold(title)
    title_folded = re.sub(r"\b1[7-9]\d{2}\s*[-–]\s*(?:1[7-9]|20)\d{2}\b", " ", title_folded)
    title_folded = re.sub(r"\b(?:1[7-9]|20)\d{2}\b", " ", title_folded)
    title_folded = re.sub(r"\s+", " ", title_folded).strip(" -–,")
    if len(title_folded) >= 16 and title_folded in question_folded:
        return 0.45
    return 0.0


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high - low < 1e-12:
        return [0.0] * len(values)
    return [(value - low) / (high - low) for value in values]


def _variable_from_json(payload: dict) -> Variable:
    values = []
    for pair in payload.get("values") or []:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            values.append((str(pair[0]), str(pair[1])))
        elif isinstance(pair, str):
            values.append((pair, pair))
    return Variable(
        code=str(payload.get("code")),
        text=str(payload.get("text") or payload.get("code")),
        time=bool(payload.get("time")),
        elimination=bool(payload.get("elimination")),
        values=values,
    )


def edition_from_json(payload: dict) -> Edition:
    return Edition(
        lang=payload["lang"],
        title=payload.get("title") or "",
        db=payload.get("db") or "",
        path=list(payload.get("path") or []),
        path_texts=list(payload.get("path_texts") or []),
        url=payload["url"],
        updated=payload.get("updated"),
        variables=[_variable_from_json(item) for item in payload.get("variables") or []],
        notes=payload.get("notes") if isinstance(payload.get("notes"), str) else None,
    )


_GENERIC_LABEL = {"year", "years", "ar", "ara", "total", "all"}


def _distinctive_label(label: str) -> bool:
    found = tokens(label)
    if not found:
        return False
    return any(token not in _GENERIC_LABEL and not token.isdigit() for token in found)


def document_text(table: Table) -> str:
    parts: list[str] = [table.id.replace(".px", "")]
    for edition in table.editions.values():
        parts.append(edition.title)
        parts.extend(edition.path_texts)
        parts.append(edition.db)
        for variable in edition.variables:
            parts.append(variable.text)
            parts.append(variable.code)
            if variable.time:
                continue
            added = 0
            for _code, label in variable.values:
                if not _distinctive_label(label):
                    continue
                parts.append(label)
                added += 1
                if added >= 24:
                    break
    return " ".join(parts)


def _entity_vocabulary(tables: list[Table]) -> tuple[set[str], set[str]]:
    """Tokens the catalogue actually publishes, split from month names.

    Titles, path labels, and variable names always count. Value labels count
    except for month-name tokens, which are recorded only when a title or a
    variable name uses them. That is what keeps "March" on a CPI codelist from
    covering a question about Mars.
    """
    general: set[str] = set()
    month_headings: set[str] = set()

    def add(token: str, heading: bool) -> None:
        if len(token) < 3 or token.isdigit():
            return
        if token in MONTH_NAMES:
            if heading:
                month_headings.add(token)
            return
        general.add(token)

    for table in tables:
        for edition in table.editions.values():
            for text in (edition.title, edition.db, *edition.path_texts):
                for token in tokens(text):
                    add(token, True)
            for variable in edition.variables:
                for token in tokens(variable.text):
                    add(token, True)
                for code, label in variable.values:
                    if _TIME_CODE.match(code) or _TIME_CODE.match(label or ""):
                        continue
                    for token in tokens(label):
                        add(token, False)
    return general, month_headings


def _table_grain(table) -> str | None:
    """month, quarter, or year, from the time codes."""
    for edition in table.editions.values():
        variable = edition.time_variable() if hasattr(edition, "time_variable") else None
        if variable is None:
            continue
        codes = " ".join(str(code) for code in variable.codes()[:12])
        if re.search(r"M\d{2}", codes, re.I):
            return "month"
        if re.search(r"Q\d", codes, re.I):
            return "quarter"
        if re.search(r"(?:19|20)\d{2}", codes):
            return "year"
    return None


def _asked_grain(question_folded: str) -> str | None:
    """The frequency the question named. A 1 January stock date is not monthly."""
    if re.search(r"\b(quarter|arsfjordung\w*)\b", question_folded):
        return "quarter"
    stock = re.sub(r"\b\d{1,2}\s*\.?\s*(?:januar|january)\b", " ", question_folded)
    if re.search(
        r"\b(january|januar|february|februar|march|mars|april|may|mai|june|juni|july|juli|august|agust|september|october|oktober|november|desember|december)\b",
        stock,
    ):
        return "month"
    if re.search(r"\b(?:19|20)\d{2}\b", question_folded):
        return "year"
    return None


class Catalogue:
    def __init__(self, tables: list[Table], embedder: Embedder, matrix: np.ndarray | None, kind: str) -> None:
        self.tables = tables
        self.by_id = {table.id: table for table in tables}
        self.embedder = embedder
        self.kind = kind
        self.docs = [tokens(document_text(table)) for table in tables]
        self.bm25 = BM25(self.docs)
        self.matrix = matrix
        self.entity_vocab, self.month_title_vocab = _entity_vocabulary(tables)
        self._vocab_buckets: dict[str, list[str]] = defaultdict(list)
        for token in self.entity_vocab:
            self._vocab_buckets[token[:3]].append(token)
        self._postings: dict[str, list[int]] = defaultdict(list)
        self._df: Counter[str] = Counter()
        self._build_postings()

    def matches_vocab(self, token: str) -> bool:
        """True when `token` is a published word, or one edit or case-ending away."""
        if token in self.entity_vocab:
            return True
        for form in lemmas(token):
            if form in self.entity_vocab:
                return True
            for other in self._vocab_buckets.get(form[:3], ()):
                if near_token(form, other):
                    return True
        # Icelandic compounds name the published word they end with
        # (heildarlosun ends with losun). A word that merely starts with a
        # common stem does not.
        if len(token) >= 10:
            for cut in range(4, len(token) - 4):
                tail = token[cut:]
                if len(tail) >= 5 and tail in self.entity_vocab:
                    return True
        return False

    def _build_postings(self) -> None:
        for index, table in enumerate(self.tables):
            seen: set[str] = set()
            for edition in table.editions.values():
                for variable in edition.variables:
                    for token in tokens(variable.text):
                        if len(token) >= 3:
                            seen.add(token)
                    if variable.time:
                        continue
                    for code, label in variable.values:
                        if _TIME_CODE.match(code) or _TIME_CODE.match(label or ""):
                            continue
                        for token in tokens(label):
                            if len(token) < 3 or token in seen:
                                continue
                            seen.add(token)
            for token in seen:
                self._postings[token].append(index)
                self._df[token] += 1

    def search(self, question: str, k: int = 8, years: list[int] | None = None) -> list[Hit]:
        if not self.tables:
            return []
        query = tokens(question, expand=True)
        lexical = self.bm25.scores(query)
        if self.matrix is not None and len(self.matrix) == len(self.tables) and self.matrix.ndim == 2:
            query_vector = self.embedder.embed_query(question)
            if query_vector.shape[0] == self.matrix.shape[1]:
                cosine = self.matrix @ query_vector
                cosine_list = [float(value) for value in cosine]
        else:
            cosine_list = [0.0] * len(self.tables)
        value_raw = [0.0] * len(self.tables)
        n = len(self.tables)
        for token in set(query):
            hits = self._postings.get(token)
            if not hits:
                continue
            # Skip labels that occur in most tables ("total", "index" sometimes).
            if self._df[token] > max(25, int(0.35 * n)):
                continue
            weight = math.log(1 + n / (1 + self._df[token]))
            for index in hits:
                value_raw[index] += weight
        coverage = [0.0] * n
        if years:
            for index, table in enumerate(self.tables):
                covered = set()
                for edition in table.editions.values():
                    covered |= edition.years()
                if covered and all(year in covered for year in years):
                    coverage[index] = 1.0
                elif covered and any(year in covered for year in years):
                    coverage[index] = 0.25
                elif covered:
                    coverage[index] = -1.0
        lexical_n = _minmax(lexical)
        cosine_n = _minmax(cosine_list)
        value_n = _minmax(value_raw)
        ranked: list[Hit] = []
        for index, table in enumerate(self.tables):
            if self.matrix is not None:
                score = 0.45 * lexical_n[index] + 0.35 * cosine_n[index] + 0.20 * value_n[index]
            else:
                score = 0.70 * lexical_n[index] + 0.30 * value_n[index]
            score += 0.2 * coverage[index]
            title_tokens = tokens(table.titles())
            if title_tokens and query:
                # Floor the denominator so a one-word title such as "Population"
                # cannot take a larger bonus than a longer title that also
                # contains the question's other words.
                overlap = len(set(title_tokens) & set(query)) / max(len(set(title_tokens)), 4)
                score += 0.35 * overlap
            score += max(_title_alignment(question, edition.title) for edition in table.editions.values())
            title_folded = " ".join(fold(edition.title) for edition in table.editions.values())
            question_folded = fold(question)
            for marker in ("earlier", "previous", "eldra", "eldri", "change of method", "overestimation", "overview", "constant price"):
                if marker in title_folded and marker not in question_folded:
                    score -= 0.2
            if any(word in title_folded for word in ("andvana", "ungbarnadau", "stillborn")):
                if not any(word in question_folded for word in ("andvana", "stillborn")):
                    score -= 0.8
            if "spa um" in title_folded or "forecast" in title_folded or "projection" in title_folded:
                if not any(word in question_folded for word in ("forecast", "projection", "spa")):
                    score -= 1.0
            # A named town is a municipality unless the question asks for an urban
            # nucleus, a locality, or districts.
            if ("immigrant" in question_folded or "innflytj" in question_folded) and "reykjavik" not in question_folded:
                asks_municipality = any(
                    word in question_folded for word in ("municipality", "sveitarfelag", "sveitarfelog")
                )
                # "Immigrants in Iceland" is the national background total. A table
                # that only splits immigrants by municipality is a different question.
                if not asks_municipality and ("municipality" in title_folded or "sveitarfelag" in title_folded):
                    score -= 1.15
                if any(word in title_folded for word in ("background", "bakgrunn", "origin")):
                    score += 0.75
            if ("unemployment" in question_folded or "atvinnuleysi" in question_folded) and (
                title_folded.startswith("unemployment") or title_folded.startswith("atvinnuleysi")
            ):
                score += 0.25
            if any(word in question_folded for word in ("born", "birth", "faedd", "faeddist")):
                if any(word in title_folded for word in ("birth", "born", "faedd", "faeding")):
                    score += 0.9
                if any(word in title_folded for word in ("pupil", "school", "skola", "nemend", "pre-primary", "leikskol")):
                    score -= 1.0
            if "reykjavik" in title_folded and "reykjavik" not in question_folded:
                score -= 0.7
            # A dated participation question is the historical election table.
            # "Voters receiving assistance" does not name participation or a month.
            if re.search(r"kosningathatttaka|participation rate", question_folded) and re.search(
                r"\b(januar|februar|mars|april|mai|juni|juli|agust|september|oktober|november|desember|january|february|march|april|may|june|july|august|october)\b",
                question_folded,
            ):
                path_folded = " ".join(
                    fold(" ".join(getattr(edition, "path_texts", []) or []))
                    for edition in table.editions.values()
                )
                if "soguleg" in path_folded:
                    score += 0.8
            for token in set(query):
                if len(token) >= 10 and token in title_folded:
                    score += 0.4
            # One named index ("wage index", "launavísitala") is not the family
            # of indices ("wage indices", "vísitölur launa").
            wants_one_index = (
                "indices" not in question_folded
                and "visitolur" not in question_folded
                and ("index" in question_folded or "visitala" in question_folded)
            )
            if wants_one_index:
                if "indices" in title_folded or "visitolur" in title_folded:
                    score -= 0.25
                elif re.search(r"\b(index|visitala)\b", title_folded):
                    score += 0.2
            if re.search(r"\b1\s*\.?\s*jan", question_folded) and not any(
                word in question_folded for word in ("starfandi", "employed")
            ):
                if "starfandi" in title_folded or "employed" in title_folded:
                    score -= 0.45
            named_town = any(token.startswith(("reykjavik", "kopavog", "akureyr", "hafnarfjord")) for token in set(query))
            population_question = any(
                word in question_folded
                for word in ("population", "lived", "inhabitants", "bjuggu", "landsmanna", "ibuum", "ibua", "ibuar", "mannfjoldi")
            )
            if population_question and "immigrant" not in question_folded and "innflytj" not in question_folded:
                if "innflytj" in title_folded or "immigrant" in title_folded:
                    score -= 0.45
                if not named_town and any(word in title_folded for word in ("thettbyli", "urban nuclei", "localit", "byggdakjarn")):
                    score -= 0.3
                if named_town and not any(word in question_folded for word in ("urban", "localit", "district", "byggdakjarn", "sveitarfelag")):
                    if ("municipality" in title_folded or "sveitarfelag" in title_folded) and (
                        "mannfjoldi" in title_folded or "population" in title_folded
                    ):
                        score += 0.35
                    if any(word in title_folded for word in ("urban nuclei", "byggdakjarn", "localit")):
                        score -= 0.2
            grain = _table_grain(table)
            asked_grain = _asked_grain(question_folded)
            if grain and asked_grain:
                if grain == asked_grain:
                    score += 0.2
                else:
                    score -= 0.55
            if any(word in question_folded for word in ("skrad", "registered", "skrasett")) and not named_town:
                if "hotel" in title_folded:
                    score -= 0.3
                if "sveitarfelag" in title_folded and "gist" in title_folded:
                    score -= 0.25
                if any(word in title_folded for word in ("skrad", "registered", "skrasett")):
                    score += 0.8
            ranked.append(
                Hit(
                    table=table,
                    score=score,
                    bm25=lexical[index],
                    cosine=cosine_list[index],
                    value_boost=value_raw[index],
                )
            )
        ranked.sort(key=lambda hit: (-round(hit.score, 6), hit.table.id))
        return ranked[:k]

    @classmethod
    def load(cls, index_dir: Path, embedder: Embedder | None = None) -> "Catalogue":
        index_dir = Path(index_dir)
        manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
        tables_path = index_dir / "tables.jsonl.gz"
        tables: list[Table] = []
        grouped: dict[str, Table] = {}
        opener = gzip.open if str(tables_path).endswith(".gz") else open
        with opener(tables_path, "rt", encoding="utf-8") as handle:
            for line in handle:
                payload = json.loads(line)
                table = grouped.get(payload["id"])
                if table is None:
                    table = Table(id=payload["id"])
                    grouped[payload["id"]] = table
                    tables.append(table)
                edition = edition_from_json(payload)
                table.editions[edition.lang] = edition
        kind = manifest.get("embedding_kind", "chargram")
        if embedder is None:
            embedder = Embedder(kind="chargram" if kind == "chargram" else "auto", model_name=manifest.get("embedding_model", ""))
            if kind == "e5" and embedder.kind != "e5":
                # Query vectors would not match the matrix. Drop embeddings.
                embedder.kind = "mismatch"
        matrix = None
        matrix_path = index_dir / "embeddings.npy"
        if matrix_path.exists() and embedder.kind == kind:
            matrix = np.load(matrix_path)
            expected = manifest.get("embedding_dim")
            width_ok = expected is None or int(matrix.shape[1]) == int(expected)
            if matrix.ndim != 2 or matrix.shape[0] != len(tables) or not width_ok:
                matrix = None
        return cls(tables, embedder, matrix, kind if matrix is not None else "none")
