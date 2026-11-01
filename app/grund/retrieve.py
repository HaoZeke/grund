"""Table retrieval for the model planner.

The listing is the bilingual catalogue walk (titles and folder paths, both
languages). Variable names and value labels come from the loaded index, which
is what a query can actually bind. The deterministic ranker is untouched.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

from grund_index.catalogue import BM25, Catalogue, Hit
from grund_index.model import Table
from grund_index.textutil import fold, tokens

_YEAR = r"(?:1[6-9]\d{2}|20\d{2})"
_SPAN = re.compile(rf"({_YEAR})\s*[-–—]\s*({_YEAR})")
_EARLIER = ("earlier", "eldra", "eldri", "historical", "soguleg")
_GENERIC = {
    "total", "alls", "all", "index", "visitala", "year", "years", "ar",
    "manudur", "month", "months", "unit", "eining", "item", "lidur",
}


def listing_path() -> Path | None:
    """Where the bilingual title listing lives, if it is on disk."""
    candidates = []
    env = os.environ.get("GRUND_CATALOGUE_JSONL", "").strip()
    if env:
        candidates.append(Path(env))
    candidates.append(Path("data/catalogue.jsonl"))
    for path in candidates:
        if path.is_file():
            return path
    return None


def title_core(title: str) -> str:
    """Folded title with a published year span taken out.

    "Fertility 1853-2025" and "Fertility" are the same name. The years are a
    coverage fact, not part of the title the question quotes.
    """
    text = fold(title)
    text = _SPAN.sub(" ", text)
    text = re.sub(r"\b(?:from|fra)\b", " ", text)
    text = re.sub(rf"\b{_YEAR}\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def closed_spans(titles: list[str]) -> list[tuple[int, int]]:
    found = []
    for title in titles:
        for start, end in _SPAN.findall(title):
            found.append((int(start), int(end)))
    return found


def _quote_bonus(question: str, titles: list[str]) -> float:
    """Longest title that the question actually repeats, as a bonus."""
    question_folded = " ".join(fold(question).split())
    best = 0.0
    for title in titles:
        core = title_core(title)
        if len(core) < 6 or core not in question_folded:
            continue
        content = [word for word in core.split() if len(word) > 2 and not word.isdigit()]
        best = max(best, 0.45 + 0.04 * len(content))
    return min(best, 1.3)


def _extra_title_penalty(question: str, titles: list[str]) -> float:
    """A sibling that adds words the question never used."""
    query = set(tokens(question, expand=True))
    penalty = 0.0
    for title in titles:
        content = [word for word in tokens(title_core(title)) if len(word) > 2 and not word.isdigit()]
        if not content:
            continue
        extras = [word for word in content if word not in query]
        overlap = len(content) - len(extras)
        if overlap >= 1 and extras:
            penalty = max(penalty, 0.08 * len(extras))
    return -min(penalty, 0.45)


def _year_score(asked: set[int], covered: set[int], spans: list[tuple[int, int]]) -> float:
    if not asked:
        return 0.0
    if covered:
        if asked <= covered:
            return 0.35
        if asked & covered:
            return -0.55
        return -1.0
    if spans:
        def covers(year: int) -> bool:
            return any(start <= year <= end for start, end in spans)

        if all(covers(year) for year in asked):
            return 0.2
        if any(covers(year) for year in asked):
            return -0.4
        return -0.8
    return 0.0


def _earlier_penalty(blob: str, question: str) -> float:
    folded_blob = fold(blob)
    folded_question = fold(question)
    for marker in _EARLIER:
        if marker in folded_blob and marker not in folded_question:
            return -0.7
    return 0.0


def _keep_label(label: str) -> str | None:
    folded = " ".join(fold(label).split())
    if len(folded) < 8 or len(folded) > 90:
        return None
    words = [word for word in tokens(label) if not word.isdigit()]
    if words and all(word in _GENERIC for word in words):
        return None
    if re.search(r"\d", folded) or len(tokens(label)) >= 2:
        return folded
    return None


class ListingRetriever:
    """BM25 over catalogue titles and paths, plus a few coverage checks."""

    def __init__(self, catalogue: Catalogue, path: Path) -> None:
        self.catalogue = catalogue
        self.path = path
        listing = _load_listing(path)
        self._titles: list[dict[str, list[str]]] = []
        self._blobs: list[str] = []
        self._spans: list[list[tuple[int, int]]] = []
        self._years: list[set[int]] = []
        self._labels: list[list[str]] = []
        documents: list[list[str]] = []
        for table in catalogue.tables:
            titles, paths = _texts_for(table, listing)
            self._titles.append(titles)
            blob = " ".join(paths.get("is", []) + paths.get("en", []) + titles.get("is", []) + titles.get("en", []))
            self._blobs.append(blob)
            self._spans.append(closed_spans(titles.get("is", []) + titles.get("en", [])))
            covered: set[int] = set()
            for edition in table.editions.values():
                covered |= edition.years()
            self._years.append(covered)
            labels = _table_labels(table)
            self._labels.append(labels)
            doc: list[str] = []
            for lang in ("is", "en"):
                doc.extend(tokens(" ".join(titles.get(lang, []))) * 3)
                doc.extend(tokens(" ".join(paths.get(lang, []))))
            for edition in table.editions.values():
                for variable in edition.variables:
                    doc.extend(tokens(variable.text))
            for label in labels:
                doc.extend(tokens(label))
            documents.append(doc)
        self._bm25 = BM25(documents)

    def search(self, question: str, language: str, k: int = 12, years: list[int] | None = None) -> list[Hit]:
        tables = self.catalogue.tables
        if not tables:
            return []
        query = tokens(question, expand=True)
        lexical = self._bm25.scores(query)
        peak = max(lexical) if lexical else 0.0
        asked = set(years or [])
        question_folded = " ".join(fold(question).split())
        value = _value_overlap(self.catalogue, query)
        ranked: list[tuple[float, float, int]] = []
        for index, table in enumerate(tables):
            titles = self._titles[index]
            primary = titles.get(language) or []
            other_lang = "en" if language == "is" else "is"
            quote = _quote_bonus(question, primary)
            if quote <= 0:
                quote = 0.6 * _quote_bonus(question, titles.get(other_lang) or [])
            bm = (lexical[index] / peak) if peak else 0.0
            score = (
                bm
                + quote
                + _extra_title_penalty(question, primary or titles.get(other_lang) or [])
                + _year_score(asked, self._years[index], self._spans[index])
                + _earlier_penalty(self._blobs[index], question)
                + _label_bonus(question_folded, self._labels[index])
                + 0.2 * value[index]
            )
            ranked.append((score, quote, index))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        hits = []
        for score, _quote, index in ranked[:k]:
            table = tables[index]
            hits.append(Hit(table=table, score=score, bm25=lexical[index], cosine=0.0, value_boost=value[index]))
        return hits


def _load_listing(path: Path) -> dict[str, dict]:
    grouped: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        bucket = grouped.setdefault(row["id"], {"titles": {"is": [], "en": []}, "paths": {"is": [], "en": []}})
        for lang in ("is", "en"):
            edition = row.get(lang) or {}
            title = edition.get("title") or ""
            if title and title not in bucket["titles"][lang]:
                bucket["titles"][lang].append(title)
            for text in edition.get("path_texts") or []:
                if text and text not in bucket["paths"][lang]:
                    bucket["paths"][lang].append(text)
            subject = row.get("subject") or ""
            if lang == "is" and subject and subject not in bucket["paths"][lang]:
                bucket["paths"][lang].append(subject)
    return grouped


def _texts_for(table: Table, listing: dict[str, dict]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    row = listing.get(table.id.removesuffix(".px"))
    if row:
        return row["titles"], row["paths"]
    titles: dict[str, list[str]] = {"is": [], "en": []}
    paths: dict[str, list[str]] = {"is": [], "en": []}
    for lang, edition in table.editions.items():
        if edition.title:
            titles.setdefault(lang, []).append(edition.title)
        for text in edition.path_texts:
            paths.setdefault(lang, []).append(text)
    return titles, paths


def _table_labels(table: Table) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for edition in table.editions.values():
        for variable in edition.variables:
            if variable.time:
                continue
            for _code, label in variable.values:
                kept = _keep_label(label)
                if kept is None or kept in seen:
                    continue
                seen.add(kept)
                found.append(kept)
                if len(found) >= 64:
                    return found
    return found


def _label_bonus(question_folded: str, labels: list[str]) -> float:
    total = 0.0
    for label in labels:
        if label in question_folded:
            total += 0.22
            if total >= 0.66:
                return 0.66
    return total


def _value_overlap(catalogue: Catalogue, query: list[str]) -> list[float]:
    n = len(catalogue.tables)
    raw = [0.0] * n
    if not n or not hasattr(catalogue, "_postings"):
        return raw
    for token in set(query):
        hits = catalogue._postings.get(token)
        if not hits:
            continue
        if catalogue._df[token] > max(25, int(0.35 * n)):
            continue
        weight = math.log(1 + n / (1 + catalogue._df[token]))
        for index in hits:
            raw[index] += weight
    peak = max(raw) if raw else 0.0
    if peak <= 0:
        return raw
    return [value / peak for value in raw]
