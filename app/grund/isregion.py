"""Population of one Icelandic region. Off unless ``GRUND_IS_KANG_REGION`` is set.

The eight landshlutar are on MAN03250. A question that names one of them,
and not a sex or a year of age, leads with that region's total. A missing
year uses the latest 1 January in the table.
"""

from __future__ import annotations

import os
import re

from grund_index.catalogue import Hit
from grund_index.textutil import fold

_TABLE = "MAN03250"
_COUNT = ("bjuggu", "bua", "ibua", "folk", "byr", "mannfjold", "lived", "live", "people", "population", "inhabitant", "headcount", "resident")
_BLOCK = ("karl", "konu", "kven", "kynsegin", "og eldri", "og yngri", "ara og", "women", "woman", " men", "older", "immigrant")


def enabled() -> bool:
    return os.environ.get("GRUND_IS_KANG_REGION", "0").strip().lower() in {"1", "on", "true", "yes"}


def _region_variable(edition):
    for variable in getattr(edition, "variables", []) or []:
        blob = fold(f"{variable.code} {variable.text}")
        if "landshlut" in blob or blob.strip() in {"region", "regions"}:
            return variable
    return None


def _text_words(question: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(question or ""))


_CASE = {"", "i", "u", "s", "is", "ar", "ir", "um", "inu", "inni", "inn", "num", "unni"}


def _word_hits(word: str, words: list[str]) -> bool:
    """A region word, or that word plus a case ending. Not a longer place name."""
    if len(word) < 4:
        return False
    for other in words:
        if other == word:
            return True
        if other.startswith(word) and other[len(word) :] in _CASE:
            return True
    return False


# English codes and the Icelandic region names are the same eight areas.
_REGION_ALIAS = {
    "east": ("austurland",),
    "west": ("vesturland",),
    "westfjords": ("vestfirdir", "vestfjarda", "vestfjord"),
    "northwest": ("nordurland vestra",),
    "northeast": ("nordurland eystra",),
    "south": ("sudurland",),
    "southwest": ("sudurnes", "sudurnesjum", "sudurnesja"),
    "capital region": ("hofudborgarsvaedi", "hofudborgarsvaedid", "hofudborgarsvaedinu"),
}


def _alias_hit(question: str, label: str) -> bool:
    folded = fold(label or "")
    words = _text_words(question)
    blob = " ".join(words)
    for alias in _REGION_ALIAS.get(folded, ()):
        if alias in blob or alias in words:
            return True
    return False


def label_is_region(question: str, label: str) -> bool:
    folded = fold(str(label or ""))
    if folded in {"alls", "total", "samtals"} or not folded:
        return False
    words = _text_words(question)
    if folded in words:
        return True
    from grund_lang.lemma import analyze

    for tok in analyze(question).tokens:
        if fold(tok.lemma or "") == folded or fold(tok.surface) == folded:
            return True
    parts = [part for part in folded.split() if len(part) >= 4]
    if bool(parts) and all(_word_hits(part, words) for part in parts):
        return True
    return _alias_hit(question, label)


def named_region(question: str, edition) -> tuple[str, str] | None:
    variable = _region_variable(edition)
    if variable is None:
        return None
    hits = []
    for code, label in variable.values:
        if label_is_region(question, str(label or "")):
            hits.append((str(code), str(label)))
    if len(hits) == 1:
        return hits[0]
    return None


def wants_region(question: str, language: str | None) -> bool:
    if not enabled():
        return False
    if language not in {None, "", "is", "en"}:
        return False
    text = fold(question or "")
    if not any(mark in text for mark in _COUNT):
        return False
    if any(mark in text for mark in _BLOCK):
        return False
    if re.search(r"\b\d{1,3}\s+ara\b", text):
        return False
    return True


def _stem(table_id: str) -> str:
    base = str(table_id).split("#", 1)[0]
    return base[:-3] if base.endswith(".px") else base


def region_value_code(variable, question: str, language: str | None, title: str) -> str | None:
    if not wants_region(question, language):
        return None
    folded_title = fold(title or "")
    if "landshlut" not in folded_title and "region" not in folded_title:
        return None
    blob = fold(f"{getattr(variable, 'code', '')} {getattr(variable, 'text', '')}")
    if "landshlut" not in blob:
        return None
    # The edition is not passed in. Match labels on this variable directly.
    hits = []
    for code, label in getattr(variable, "values", []) or []:
        if label_is_region(question, str(label or "")):
            hits.append(str(code))
    if len(hits) == 1:
        return hits[0]
    return None


def region_word_covered(token: str, question: str, language: str | None, edition, chosen: dict) -> bool:
    if not wants_region(question, language) or edition is None:
        return False
    if "landshlut" not in fold(getattr(edition, "title", "") or ""):
        return False
    variable = _region_variable(edition)
    if variable is None:
        return False
    codes = list((chosen or {}).get(variable.code) or [])
    if len(codes) != 1:
        return False
    label = variable.label(codes[0]) if hasattr(variable, "label") else ""
    if not label_is_region(question, str(label or "")):
        return False
    folded = fold(token)
    from grund_lang.lemma import analyze

    for tok in analyze(question).tokens:
        if fold(tok.surface) == folded and (fold(tok.lemma or "") == fold(label) or fold(label).startswith(fold(tok.lemma or ""))):
            return True
    return fold(label).startswith(folded) or folded.startswith(fold(label))


def _labels(result: dict) -> list[str]:
    cells: list = []
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    cells.extend(source.get("cells") or [])
    for claim in result.get("claims") or []:
        if isinstance(claim, dict):
            cells.extend(claim.get("cells") or [])
    found: list[str] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        raw = cell.get("labels")
        if isinstance(raw, dict):
            found.extend(fold(str(value)) for value in raw.values())
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    found.append(fold(str(item.get("label") or "")))
    return found


def region_cell_clears(question: str, language: str | None, produced: dict, verdict: dict | None) -> bool:
    """The region total is the cell. 'býr fólk' is not printed on the table."""
    if not wants_region(question, language):
        return False
    reason = str((verdict or {}).get("reason") or "")
    if reason not in {"cited cell does not match the question", "breakdown not asked for"}:
        return False
    table = produced.get("table")
    if _stem(str(getattr(table, "id", "") or "")) != _TABLE:
        return False
    claims = produced.get("claims") or []
    labels: list[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            raw = cell.get("labels")
            if isinstance(raw, dict):
                labels.extend(str(value) for value in raw.values())
            elif isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        labels.append(str(item.get("label") or ""))
    if any(fold(label) in {"karlar", "konur"} for label in labels):
        return False
    return any(label_is_region(question, label) for label in labels)


def region_ranker(question: str, language: str | None, ranker: dict) -> dict | None:
    if not wants_region(question, language):
        return None
    if ranker.get("refused") or ranker.get("value") in (None, ""):
        return None
    if _stem(str(ranker.get("table_id") or "")) != _TABLE:
        return None
    labels = _labels(ranker)
    if any(label in {"karlar", "konur"} for label in labels):
        return None
    regions = [label for label in labels if label not in {"alls", "total", "samtals"} and not label.isdigit() and "ara" not in label]
    if not any(label_is_region(question, label) for label in regions):
        return None
    chosen = dict(ranker)
    source = dict(chosen.get("source") or {})
    source["lookalike_resolved"] = True
    source["is_region"] = True
    chosen["source"] = source
    return chosen


def apply_is_region(catalogue, hits: list[Hit], question: str, language: str | None) -> list[Hit]:
    if not wants_region(question, language):
        return hits
    table = catalogue.by_id.get(_TABLE + ".px") or catalogue.by_id.get(_TABLE)
    if table is None:
        return hits
    edition = table.edition(language or "is") or table.edition("is") or table.edition("en")
    if edition is None or named_region(question, edition) is None:
        return hits
    from grund.bind import bind
    from grund.parse import parse_question

    binding = bind(edition, parse_question(question, "is"))
    if binding is None:
        return hits
    code, _label = named_region(question, edition)
    picked = []
    for selection in binding.selections:
        picked.extend(str(item) for item in (selection.get("selection") or {}).get("values") or [])
    if code not in picked:
        return hits
    kept = [hit for hit in hits if _stem(hit.table.id) != _TABLE]
    score = max((hit.score for hit in kept), default=0.0) + 1.0
    lead = Hit(table=table, score=score, bm25=0.0, cosine=0.0, value_boost=0.0)
    return [lead] + kept
