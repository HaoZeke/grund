"""Prefer the curated base table when a one-digit sibling has the same cell.

``GRUND_SIBLING_GUARD`` is off unless it is ``1``, ``true``, ``yes``, or ``on``.
Two catalogue ids share a stem when they have the same length and differ by
one character. The base list is the headline series already used by the
gates. A figure that is already on that list stays there. A figure on the
other sibling moves to the base table when that table returns the same
number. A different number is a different cell and is left where it was.
"""

from __future__ import annotations

import os

# Headline series. A statement on one of these is not moved.
_BASE = {
    "MAN00000", "MAN00101", "MAN01400", "MAN02005", "MAN03250", "MAN05100",
    "MAN05210", "MAN06100", "MAN43000",
    "VIN00911", "VIN00920", "VIN00931",
    "UTA06002",
    "LAU04000", "LAU04001",
    "THJ01102", "THJ01103",
    "VIS01000", "VIS01005", "VIS13401",
    "SAM01202", "SAM01601",
    "SKO02101", "PEN02101",
}


def enabled() -> bool:
    return os.environ.get("GRUND_SIBLING_GUARD", "").strip().lower() in {"1", "true", "yes", "on"}


def _stem(table_id: str) -> str:
    return str(table_id or "").split("#", 1)[0].removesuffix(".px")


def shares_stem(left: str, right: str) -> bool:
    """One variant digit. MAN01400 and MAN01401. Not two different series."""
    if not left or not right or left == right or len(left) != len(right):
        return False
    return sum(a != b for a, b in zip(left, right)) == 1


def siblings_of(ids: list[str], stem: str) -> list[str]:
    found = []
    for raw in ids:
        other = _stem(raw)
        if shares_stem(stem, other) and other not in found:
            found.append(other)
    return found


def _same(left, right) -> bool:
    try:
        return abs(float(left) - float(right)) < 0.051
    except (TypeError, ValueError):
        return False


def _query(result: dict) -> list | None:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    query = source.get("query")
    if isinstance(query, list) and query and all(isinstance(item, dict) and item.get("code") for item in query):
        return query
    return None


def _edition(catalogue, stem: str, language: str | None):
    table = catalogue.by_id.get(stem + ".px") or catalogue.by_id.get(stem)
    if table is None:
        return None, None
    edition = table.edition(language or "") or table.edition("en") or table.edition("is")
    return table, edition


def _label_code(label: str, by_label: dict[str, str]) -> str | None:
    """Exact label, or the one base label that is a long prefix of this one."""
    if label in by_label:
        return by_label[label]
    found = []
    for other, code in by_label.items():
        if len(other) < 8 or len(label) < 8:
            continue
        if label.startswith(other) or other.startswith(label):
            found.append(code)
    if len(set(found)) == 1:
        return found[0]
    return None


def _translate(source_edition, base_edition, query: list) -> list | None:
    """Same selected labels on the base table, even when the variable codes differ."""
    from grund_index.textutil import fold

    translated = []
    for entry in query:
        variable = source_edition.variable(entry["code"])
        if variable is None:
            return None
        raw_codes = [str(code) for code in entry["selection"]["values"]]
        labels = [fold(str(variable.label(code) or code)) for code in raw_codes]
        if variable.time:
            target = base_edition.time_variable()
            if target is None:
                return None
            by_code = {str(code): str(code) for code, _label in target.values}
            by_label = {fold(str(label)): str(code) for code, label in target.values}
            mapped = []
            for code, label in zip(raw_codes, labels):
                if code in by_code:
                    mapped.append(code)
                elif label in by_label:
                    mapped.append(by_label[label])
                else:
                    return None
            translated.append({"code": target.code, "selection": {"filter": "item", "values": mapped}})
            continue
        chosen = None
        for other in base_edition.variables:
            if other.time:
                continue
            by_label = {fold(str(label)): str(code) for code, label in other.values}
            mapped = [_label_code(label, by_label) for label in labels]
            if all(code is not None for code in mapped):
                chosen = (other.code, mapped)
                break
        if chosen is None:
            return None
        translated.append({"code": chosen[0], "selection": {"filter": "item", "values": chosen[1]}})
    return translated


def _value_on(engine, parsed, stem: str, query: list, source_edition):
    language = getattr(parsed, "language", None)
    table, edition = _edition(engine.catalogue, stem, language)
    if table is None or edition is None or source_edition is None:
        return None
    translated = _translate(source_edition, edition, query)
    if not translated:
        return None
    from grund.bind import Binding
    from grund.compute import extract_rows
    from grund.validator import validate

    try:
        validate(edition, translated)
        binding = Binding(
            edition=edition,
            selections=translated,
            operation="level",
            score=0,
            time_var=None,
            time_codes=[],
            notes=["sibling-base"],
        )
        payload, _audit = engine._fetch(table, edition, binding)
        rows = [row for row in extract_rows(payload, edition) if row.get("value") not in {None, ".", ".."}]
    except Exception:
        return None
    if len(rows) != 1:
        return None
    return rows[0].get("value")


def adjust(engine, parsed, result: dict):
    """A result citing the base table, or None to keep the statement."""
    if not enabled() or engine is None or result.get("refused") or result.get("value") in (None, ""):
        return None
    catalogue = getattr(engine, "catalogue", None)
    if catalogue is None:
        return None
    stem = _stem(result.get("table_id") or "")
    if not stem or stem in _BASE:
        return None
    query = _query(result)
    if query is None:
        return None
    _table, source_edition = _edition(catalogue, stem, getattr(parsed, "language", None))
    if source_edition is None:
        return None
    bases = [item for item in siblings_of(list(catalogue.by_id), stem) if item in _BASE]
    matched = []
    for base in bases:
        got = _value_on(engine, parsed, base, query, source_edition)
        if _same(got, result.get("value")):
            matched.append(base)
    if len(matched) != 1:
        return None
    base = matched[0]
    chosen = dict(result)
    suffix = ".px" if str(result.get("table_id") or "").endswith(".px") else ""
    chosen["table_id"] = base + suffix
    tables = []
    for item in chosen.get("tables") or []:
        text = str(item)
        tables.append((base + ".px") if _stem(text) == stem else text)
    if tables:
        chosen["tables"] = tables
    source = dict(chosen.get("source") or {})
    source["sibling_from"] = stem
    source["sibling_base"] = base
    chosen["source"] = source
    return chosen
