"""Trust guard for an optional extra-context panel.

The verified answer comes from ``POST /api/ask``. This module does not change
that answer and does not fetch anything. It only decides which sentences of
an elaboration may be shown, and it stamps the text it keeps.

Figures the guard treats as verified live in these fields:

* ``answer`` (the prose sentence)
* ``value`` and ``value_display``
* ``source.cells[]`` values, periods, keys, and labels
* ``source.derived.value`` and ``source.derived.inputs``
* ``claims[].value`` and ``claims[].cells[]``
* ``path_pair.left`` / ``path_pair.right`` values and cells

Table ids, URLs, retrieval timestamps, ``elapsed_ms``, and ``source.title``
are not figures. A title such as ``2015=100`` must not unlock ``100``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse

LABEL_EN = "Extra context (LLM, unverified)"
LABEL_IS = "Aukalegt samhengi (mállíkan, óstaðfest)"

_PERCENT_OPS = {"share", "share_percent", "yoy_pct", "yoy", "pct_change", "percent"}
_YEAR = r"(?:1[6-9]\d{2}|20\d{2})"
_SPACE_CHARS = " \u00a0\u202f\u2009"
_SPACE_CLASS = "[" + _SPACE_CHARS + "]"
_SPACE_TRANSLATE = {ord(ch): " " for ch in _SPACE_CHARS if ch != " "}

_URL = re.compile(r"https?://[^\s<>\]]+")
_TABLE_ID = re.compile(r"\b([A-Za-z]{3})(\d{4,5})(?:\.px)?\b")
_ISO = re.compile(
    rf"\b({_YEAR})-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
    rf"(?:T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:Z|[+-](?:[01]\d|2[0-3]):?[0-5]\d)?)?\b"
)
_MONTH_CODE = re.compile(rf"\b({_YEAR})[Mm](\d{{1,2}})\b")
_BARE_QUARTER = re.compile(r"\bQ([1-4])\b", re.IGNORECASE)
_QUARTER_Q_YEAR = re.compile(rf"\bQ([1-4])(?:\s+of)?\s+({_YEAR})\b", re.IGNORECASE)
_QUARTER_YEAR_Q = re.compile(rf"\b({_YEAR})\s*-?\s*Q([1-4])\b", re.IGNORECASE)
_QUARTER_ORDINAL = re.compile(
    rf"\b([1-4])(?:st|nd|rd|th)\s+quarter(?:\s+of)?\s+({_YEAR})\b",
    re.IGNORECASE,
)
_QUARTER_IS_DOT = re.compile(
    rf"\b([1-4])\.\s*ársfjórðung\w*\s+({_YEAR})\b",
    re.IGNORECASE,
)
_QUARTER_IS_WORD = re.compile(
    rf"\b(fyrsta|fyrsti|annar|annan|þriðja|þriðji|fjórða|fjórði)\s+ársfjórðung\w*\s+({_YEAR})\b",
    re.IGNORECASE,
)
_IS_QUARTER_WORD = {
    "fyrsta": 1,
    "fyrsti": 1,
    "annar": 2,
    "annan": 2,
    "þriðja": 3,
    "þriðji": 3,
    "fjórða": 4,
    "fjórði": 4,
}

_IS_GROUP = re.compile(r"\d{1,3}(?:\.\d{3}){2,}(?:,\d+)?|\d{1,3}(?:\.\d{3})+,\d+")
_EN_GROUP = re.compile(r"\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?|\d{1,3}(?:,\d{3})+\.\d+")
_SPACE_GROUP = re.compile(rf"\d{{1,3}}(?:{_SPACE_CLASS}\d{{3}})+(?:[.,]\d+)?")
_DECIMAL = re.compile(r"\d+[.,]\d+")
_INT = re.compile(r"\d+")
_NUMBER_PATTERNS = (_IS_GROUP, _EN_GROUP, _SPACE_GROUP, _DECIMAL, _INT)
_PERCENT_TAIL = re.compile(
    r"\s*(?:%|percent(?:age)?\b|pr[oó]sent\w*\b)",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"“«(A-ZÁÉÍÓÚÝÞÆÖÐ])")

_FETCH = re.compile(r"\[fetch:\s*([A-Za-z]{3}\d{4,5})(?:\.px)?\s*\]", re.IGNORECASE)
_CALC = re.compile(r"\[calc:\s*([A-Za-z0-9_-]+)\s*\]", re.IGNORECASE)
_SOURCE = re.compile(r"\[source:\s*(https?://[^\]\s]+)\s*\]", re.IGNORECASE)
_INFERRED = re.compile(r"\(\s*(?:inferred|ályktun|alyktun)\s*\)", re.IGNORECASE)
_MARKERS = (_SOURCE, _FETCH, _CALC)

_CAUSAL = re.compile(
    r"\b(?:because|caused|causes|causing|due to|owing to|as a result of|"
    r"leads to|led to|driven by|thanks to|resulted in|results from|"
    r"vegna|olli|ollu|orsaka(?:ði|di)?|orsök|af því að|leiddi til|leiðir til|"
    r"skýrist af|af völdum|þess vegna|sökum)\b",
    re.IGNORECASE,
)
_FORECAST = re.compile(
    r"\b(?:will|won't|shall|going to|expected to|is expected|"
    r"forecast(?:s|ed)?|project(?:ed|ion|s)|predict(?:ed|s|ion)?|"
    r"likely to|on track to|munu|mun|muni|búist við|"
    r"spá(?:ð|ir|r)?|gert ráð fyrir|líklegt)\b",
    re.IGNORECASE,
)

_STRICT_HEADINGS = {"from the data", "úr gögnunum", "frá gögnunum"}
_BEYOND_HEADINGS = {"beyond the data", "handan gagnanna"}

_ZW0 = "\u200b"
_ZW1 = "\u200c"
_ZW_START = "\u200d\u200b\u200c"
_ZW_END = "\u200c\u200b\u200d"
_ZW_HIDDEN = frozenset("\u200b\u200c\u200d\u2060")


class ElabGuardError(Exception):
    """The guard cannot stamp or check provenance."""


@dataclass(frozen=True)
class NumberSpan:
    """One figure a reader would take from the text.

    ``kind`` is ``cardinal``, ``percent``, ``year``, or ``quarter``.
    ``value`` is the figure, not a percent rewritten as a fraction:
    ``12,5%`` is ``Decimal('12.5')`` with kind ``percent``.
    A quarter is not a free cardinal, so ``Q3`` does not allow the number 3.
    """

    raw: str
    value: Decimal
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class WatermarkCheck:
    ok: bool
    short_id: str | None = None
    reason: str | None = None

    def __bool__(self) -> bool:
        return self.ok


def extract_numbers(text: str, lang: str | None = "en") -> list[NumberSpan]:
    """Read figures from ``text`` in Icelandic or English grouping.

    Unambiguous forms do not depend on ``lang``: ``1.234,5``, ``1,234.5``,
    ``1.234.567``, ``8 476 511``, and a comma or dot whose fraction is not
    exactly three digits. A single group of three (``1.234`` or ``1,234``)
    follows ``lang``. ``Q3 2024``, ``2024Q3``, and ``2024M06`` contribute
    the year, and the quarter when one is written. Table ids and URLs contribute
    nothing.
    """

    language = _lang(lang)
    if not text:
        return []
    taken: list[tuple[int, int]] = []
    hits: list[NumberSpan] = []

    def overlaps(start: int, end: int) -> bool:
        return any(not (end <= left or start >= right) for left, right in taken)

    def occupy(start: int, end: int) -> None:
        taken.append((start, end))

    for match in _URL.finditer(text):
        if not overlaps(*match.span()):
            occupy(*match.span())

    for match in _TABLE_ID.finditer(text):
        if overlaps(*match.span()):
            continue
        digits = match.group(2)
        if match.group(0).lower().endswith(".px"):
            occupy(*match.span())
            continue
        if len(digits) == 4 and Decimal(digits) >= 1600 and Decimal(digits) <= 2099:
            continue
        occupy(*match.span())

    for match in _ISO.finditer(text):
        if overlaps(*match.span()):
            continue
        occupy(*match.span())
        hits.append(_span(match.group(1), Decimal(match.group(1)), "year", match.start(1), match.end(1)))

    for match in _QUARTER_Q_YEAR.finditer(text):
        _add_quarter(hits, taken, match, match.group(1), match.group(2), overlaps, occupy)
    for match in _QUARTER_YEAR_Q.finditer(text):
        _add_quarter(hits, taken, match, match.group(2), match.group(1), overlaps, occupy)
    for match in _QUARTER_ORDINAL.finditer(text):
        _add_quarter(hits, taken, match, match.group(1), match.group(2), overlaps, occupy)
    for match in _QUARTER_IS_DOT.finditer(text):
        _add_quarter(hits, taken, match, match.group(1), match.group(2), overlaps, occupy)
    for match in _QUARTER_IS_WORD.finditer(text):
        word = match.group(1).casefold()
        quarter = _IS_QUARTER_WORD.get(word)
        if quarter is None or overlaps(*match.span()):
            continue
        occupy(*match.span())
        hits.append(_span(match.group(1), Decimal(quarter), "quarter", match.start(1), match.end(1)))
        hits.append(_span(match.group(2), Decimal(match.group(2)), "year", match.start(2), match.end(2)))
    for match in _BARE_QUARTER.finditer(text):
        if overlaps(*match.span()):
            continue
        occupy(*match.span())
        hits.append(_span(match.group(0), Decimal(match.group(1)), "quarter", match.start(), match.end()))
    for match in _MONTH_CODE.finditer(text):
        if overlaps(*match.span()):
            continue
        occupy(*match.span())
        hits.append(_span(match.group(1), Decimal(match.group(1)), "year", match.start(1), match.end(1)))

    index = 0
    length = len(text)
    while index < length:
        if not text[index].isdigit() or _inside(index, taken):
            index += 1
            continue
        body = _longest_number(text, index)
        if body is None:
            index += 1
            continue
        end = index + len(body)
        if overlaps(index, end):
            index += 1
            continue
        percent = _PERCENT_TAIL.match(text, end)
        kind = "percent" if percent else "cardinal"
        if percent:
            end = percent.end()
        sign = 1
        start = index
        if index > 0 and text[index - 1] in "-−" and (index == 1 or not text[index - 2].isdigit()):
            sign = -1
            start = index - 1
        try:
            value = _parse_token(body, language) * sign
        except (InvalidOperation, ValueError):
            index += 1
            continue
        if kind == "cardinal" and sign > 0 and re.fullmatch(r"\d{4}", body):
            if Decimal(1600) <= value <= Decimal(2099):
                kind = "year"
        raw = text[start:end]
        hits.append(_span(raw, value, kind, start, end))
        occupy(start, end)
        index = end

    hits.sort(key=lambda hit: (hit.start, hit.end))
    return hits


def check(
    elaboration: str,
    verified_answer_json,
    question: str,
    lang: str | None = "en",
    tool_records: list | None = None,
) -> dict:
    """Return the elaboration with unsupported sentences removed.

    A number may stay when it appears in the verified answer or the question.
    Years written in the question count. In a ``From the data`` section that
    is the whole rule.

    In a ``Beyond the data`` section a new number may also stay when the same
    sentence carries a marker:

    * ``[fetch:TABLEID]`` and the number is one of that fetch's cell figures
    * ``[calc:N]`` and the number matches that calc ``result`` within rounding
    * ``[source:URL]`` and the host is ``island.is`` or a subdomain, the URL
      matches a ``kind: source`` record, and the number appears in that
      record's ``text``
    * ``(inferred)`` or ``(ályktun)``, and the sentence does not also cite a
      fetch, calc, or source that fails to cover the number

    An off-domain ``[source:URL]``, including a lookalike such as
    ``island.is.evil.com``, drops the whole sentence. Unmarked new numbers
    are dropped in both sections. Causality and forecast wording is flagged
    and left in place when the numbers themselves are allowed.

    ``tool_records`` items look like
    ``{id, kind: fetch|calc|source, table, cells|expression, result, url, text}``.
    """

    language = _lang(lang)
    records = [item for item in (tool_records or []) if isinstance(item, dict)]
    allowed = _allowed_numbers(verified_answer_json, question or "", language)
    dropped: list[str] = []
    flags: list[dict] = []
    lines: list[str] = []
    for mode, kind, text in _blocks(elaboration or ""):
        if kind == "heading":
            lines.append(text)
            continue
        if kind == "blank":
            lines.append("")
            continue
        flags.extend(_claim_flags(text))
        if _sentence_allowed(text, mode, allowed, records, language):
            lines.append(text)
        else:
            dropped.append(text)
    rendered = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return {
        "text": rendered,
        "dropped_sentences": dropped,
        "flags": flags,
        "ok": not dropped,
    }


def watermark(text: str, meta: dict) -> str:
    """Add the visible unverified label and an invisible provenance marker.

    The marker is a zero-width encoding of a short id and an HMAC-SHA256 over
    ``answer hash | model | timestamp``. The key is ``GRUND_ELAB_HMAC_KEY``.
    """

    label = _label(meta)
    payload = _payload(meta)
    return f"{label}{_zw_encode(payload)}\n{text or ''}"


def verify_watermark(text: str, meta: dict) -> WatermarkCheck:
    """Check the visible label and the HMAC against ``meta`` and the env key."""

    label = _label(meta)
    if not text:
        return WatermarkCheck(False, reason="marker missing")
    first = text.splitlines()[0]
    if _visible(first) != label:
        return WatermarkCheck(False, reason="label missing")
    found = _zw_decode_all(text)
    if not found:
        return WatermarkCheck(False, reason="marker missing")
    try:
        expected = _mac(meta)
    except ElabGuardError as exc:
        return WatermarkCheck(False, reason=str(exc))
    for payload in found:
        parts = payload.split("|")
        if len(parts) != 3 or parts[0] != "v1":
            continue
        short_id, mac = parts[1], parts[2]
        if short_id != mac[:8]:
            continue
        if hmac.compare_digest(mac, expected):
            return WatermarkCheck(True, short_id=short_id)
    return WatermarkCheck(False, reason="mismatch")


def _lang(lang: str | None) -> str:
    token = str(lang or "en").lower().replace("_", "-")
    if token == "is" or token.startswith("is-"):
        return "is"
    return "en"


def _span(raw: str, value: Decimal, kind: str, start: int, end: int) -> NumberSpan:
    return NumberSpan(raw, value, kind, start, end)


def _add_quarter(hits, taken, match, quarter, year, overlaps, occupy) -> None:
    if overlaps(*match.span()):
        return
    occupy(*match.span())
    hits.append(_span(match.group(0), Decimal(quarter), "quarter", match.start(), match.end()))
    hits.append(_span(year, Decimal(year), "year", match.start(), match.end()))


def _inside(index: int, taken: list[tuple[int, int]]) -> bool:
    return any(left <= index < right for left, right in taken)


def _longest_number(text: str, index: int) -> str | None:
    best = None
    for pattern in _NUMBER_PATTERNS:
        match = pattern.match(text, index)
        if match is None:
            continue
        if best is None or len(match.group(0)) > len(best):
            best = match.group(0)
    return best


def _parse_token(raw: str, lang: str) -> Decimal:
    text = raw.translate(_SPACE_TRANSLATE)
    if re.fullmatch(r"\d{1,3}(?:\.\d{3}){2,}(?:,\d+)?|\d{1,3}(?:\.\d{3})+,\d+", text):
        return Decimal(text.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?|\d{1,3}(?:,\d{3})+\.\d+", text):
        return Decimal(text.replace(",", ""))
    if re.fullmatch(r"\d{1,3}(?: \d{3})+,\d+", text):
        return Decimal(text.replace(" ", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?: \d{3})+(?:\.\d+)?", text):
        return Decimal(text.replace(" ", ""))
    if re.fullmatch(r"\d{1,3}\.\d{3}", text):
        if lang == "is":
            return Decimal(text.replace(".", ""))
        return Decimal(text)
    if re.fullmatch(r"\d{1,3},\d{3}", text):
        if lang == "en":
            return Decimal(text.replace(",", ""))
        return Decimal(text.replace(",", "."))
    if "," in text and "." not in text:
        return Decimal(text.replace(",", "."))
    return Decimal(text.replace(" ", ""))


def _heading_mode(line: str) -> str | None:
    text = re.sub(r"^#{1,6}\s*", "", line.strip())
    text = text.strip(" :*").casefold()
    if text in _STRICT_HEADINGS:
        return "strict"
    if text in _BEYOND_HEADINGS:
        return "beyond"
    return None


def _sentences(paragraph: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(paragraph.strip())
    return [part.strip() for part in parts if part.strip()]


def _blocks(elaboration: str):
    mode = "strict"
    buffer: list[str] = []
    items: list[tuple[str, str, str]] = []

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        text = " ".join(buffer)
        buffer = []
        for sentence in _sentences(text):
            items.append((mode, "sentence", sentence))

    for line in elaboration.splitlines():
        if not line.strip():
            flush()
            items.append((mode, "blank", ""))
            continue
        heading = _heading_mode(line)
        if heading is not None:
            flush()
            mode = heading
            items.append((mode, "heading", line.strip()))
            continue
        buffer.append(line.strip())
    flush()
    return items


def _claim_flags(sentence: str) -> list[dict]:
    found = []
    if _CAUSAL.search(sentence):
        found.append({"kind": "causality", "sentence": sentence})
    if _FORECAST.search(sentence):
        found.append({"kind": "forecast", "sentence": sentence})
    return found


def _allowed_numbers(answer, question: str, lang: str) -> list[NumberSpan]:
    hits = list(extract_numbers(question or "", lang))
    payload = _coerce_answer(answer)
    if isinstance(payload, str):
        hits.extend(extract_numbers(payload, lang))
        return hits
    if not isinstance(payload, dict):
        return hits
    answer_lang = _lang(payload.get("language") or lang)
    percent = _percent_answer(payload)
    prose = payload.get("answer")
    if isinstance(prose, str):
        hits.extend(extract_numbers(prose, answer_lang))
    hits.extend(_figure_hits(payload.get("value"), answer_lang, percent))
    hits.extend(_display_hits(payload.get("value_display"), payload.get("value"), answer_lang, percent))
    source = payload.get("source")
    if isinstance(source, dict):
        hits.extend(_cells_hits(source.get("cells"), answer_lang))
        hits.extend(_derived_hits(source.get("derived"), answer_lang, percent))
    for claim in payload.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        claim_percent = percent or str(claim.get("op") or claim.get("operation") or "").lower() in _PERCENT_OPS
        hits.extend(_figure_hits(claim.get("value"), answer_lang, claim_percent))
        hits.extend(_cells_hits(claim.get("cells"), answer_lang))
    pair = payload.get("path_pair")
    if isinstance(pair, dict):
        for side in ("left", "right"):
            card = pair.get(side)
            if not isinstance(card, dict):
                continue
            hits.extend(_figure_hits(card.get("value"), answer_lang, False))
            hits.extend(_figure_hits(card.get("value_display"), answer_lang, False))
            hits.extend(_cells_hits(card.get("cells"), answer_lang))
    return hits


def _coerce_answer(answer):
    if not isinstance(answer, str):
        return answer
    stripped = answer.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            loaded = json.loads(stripped)
        except json.JSONDecodeError:
            return answer
        if isinstance(loaded, dict):
            return loaded
    return answer


def _percent_answer(answer: dict) -> bool:
    names = [answer.get("operation"), answer.get("op")]
    source = answer.get("source")
    if isinstance(source, dict):
        names.append(source.get("operation"))
        derived = source.get("derived")
        if isinstance(derived, dict):
            names.append(derived.get("name"))
    return any(str(name or "").lower() in _PERCENT_OPS for name in names)


def _display_hits(display, raw_value, lang: str, percent: bool) -> list[NumberSpan]:
    """Keep a grouped display only when it is the same figure as ``value``.

    ``value_display`` follows the answer language. A wrong language must not
    turn ``394,324`` into the extra figure ``394.324``.
    """

    candidates = _figure_hits(display, lang, percent)
    anchors = {hit.value for hit in _coerce_figures(raw_value, "en") if hit.kind != "quarter"}
    if not anchors:
        return candidates
    matched = [hit for hit in candidates if hit.kind == "quarter" or hit.value in anchors]
    if matched:
        return matched
    other = "en" if lang == "is" else "is"
    alternate = _figure_hits(display, other, percent)
    matched = [hit for hit in alternate if hit.value in anchors]
    if matched:
        return matched
    return []


def _figure_hits(raw, lang: str, percent: bool) -> list[NumberSpan]:
    hits = _coerce_figures(raw, lang)
    if not percent:
        return hits
    tagged = []
    for hit in hits:
        if hit.kind in {"quarter", "year"}:
            tagged.append(hit)
        else:
            tagged.append(replace(hit, kind="percent"))
    return tagged


def _coerce_figures(raw, lang: str) -> list[NumberSpan]:
    if raw is None or isinstance(raw, bool):
        return []
    if isinstance(raw, Decimal):
        return [_span(str(raw), raw, "cardinal", 0, 0)]
    if isinstance(raw, int) and not isinstance(raw, bool):
        return [_span(str(raw), Decimal(raw), "cardinal", 0, 0)]
    if isinstance(raw, float):
        return [_span(str(raw), Decimal(str(raw)), "cardinal", 0, 0)]
    text = str(raw).strip()
    if not text:
        return []
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return [_span(text, Decimal(text), "cardinal", 0, 0)]
    return extract_numbers(text, lang)


def _cells_hits(cells, lang: str) -> list[NumberSpan]:
    hits: list[NumberSpan] = []
    for cell in _each_cell(cells):
        if not isinstance(cell, dict):
            hits.extend(_coerce_figures(cell, lang))
            continue
        hits.extend(_coerce_figures(cell.get("value"), lang))
        hits.extend(_coerce_figures(cell.get("period"), lang))
        key = cell.get("key")
        if isinstance(key, list):
            for item in key:
                hits.extend(_coerce_figures(item, lang))
        elif key is not None:
            hits.extend(_coerce_figures(key, lang))
        labels = cell.get("labels")
        if isinstance(labels, dict):
            for item in labels.values():
                hits.extend(_coerce_figures(item, lang))
        elif isinstance(labels, list):
            for item in labels:
                if isinstance(item, dict):
                    hits.extend(_coerce_figures(item.get("label"), lang))
                    hits.extend(_coerce_figures(item.get("code"), lang))
                else:
                    hits.extend(_coerce_figures(item, lang))
    return hits


def _derived_hits(derived, lang: str, percent: bool) -> list[NumberSpan]:
    if not isinstance(derived, dict):
        return []
    derived_percent = percent or str(derived.get("name") or "").lower() in _PERCENT_OPS
    hits = _figure_hits(derived.get("value"), lang, derived_percent)
    for item in derived.get("inputs") or []:
        hits.extend(_coerce_figures(item, lang))
    return hits


def _each_cell(cells):
    if cells is None:
        return
    if isinstance(cells, dict):
        yield cells
        return
    if isinstance(cells, (str, int, float, Decimal)):
        yield cells
        return
    if isinstance(cells, list):
        yield from cells


def _strip_markers(sentence: str) -> str:
    cleaned = sentence
    for pattern in _MARKERS:
        cleaned = pattern.sub(" ", cleaned)
    return cleaned


def _sentence_allowed(sentence, mode, allowed, records, lang) -> bool:
    source_urls = _SOURCE.findall(sentence)
    if any(island_host(url) is None for url in source_urls):
        return False
    hits = extract_numbers(_strip_markers(sentence), lang)
    if not hits:
        return True
    if mode != "beyond":
        return all(_covers(hit, allowed, percent_strict=True) for hit in hits)

    fetch_pools = [_fetch_pool(table, records, lang) for table in _FETCH.findall(sentence)]
    calc_values = [_calc_result(cid, records, lang) for cid in _CALC.findall(sentence)]
    source_pools = [_source_pool(url, records, lang) for url in source_urls]
    explicit = bool(fetch_pools or calc_values or source_pools)
    inferred = _INFERRED.search(sentence) is not None
    for hit in hits:
        if _covers(hit, allowed, percent_strict=True):
            continue
        if any(_covers(hit, pool, percent_strict=True) for pool in fetch_pools):
            continue
        if hit.kind != "quarter" and any(
            value is not None and _within_rounding(hit.value, value) for value in calc_values
        ):
            continue
        if any(_covers(hit, pool, percent_strict=True) for pool in source_pools):
            continue
        if inferred and not explicit and hit.kind != "quarter":
            continue
        return False
    return True


def _covers(hit: NumberSpan, pool: list[NumberSpan], *, percent_strict: bool) -> bool:
    for other in pool:
        if hit.kind == "quarter" or other.kind == "quarter":
            if hit.kind == other.kind and hit.value == other.value:
                return True
            continue
        if hit.value != other.value:
            continue
        if percent_strict and hit.kind == "percent" and other.kind != "percent":
            continue
        return True
    return False


def _within_rounding(shown: Decimal, result: Decimal) -> bool:
    if shown == result:
        return True
    exponent = shown.as_tuple().exponent
    if not isinstance(exponent, int):
        return False
    places = -exponent if exponent < 0 else 0
    quantum = Decimal(1).scaleb(-places)
    try:
        rounded = result.quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return False
    return rounded == shown


def _table_stem(value: str) -> str:
    match = re.search(r"[A-Za-z]{3}\d{4,5}", str(value or ""))
    return match.group(0).upper() if match else ""


def _fetch_pool(table: str, records: list[dict], lang: str) -> list[NumberSpan]:
    stem = _table_stem(table)
    hits: list[NumberSpan] = []
    for record in records:
        if str(record.get("kind") or "").lower() != "fetch":
            continue
        record_stem = _table_stem(str(record.get("table") or "")) or _table_stem(str(record.get("id") or ""))
        if record_stem != stem:
            continue
        hits.extend(_cells_hits(record.get("cells"), lang))
    return hits


def _calc_result(cid: str, records: list[dict], lang: str) -> Decimal | None:
    for record in records:
        if str(record.get("kind") or "").lower() != "calc":
            continue
        if str(record.get("id")) != str(cid):
            continue
        hits = _coerce_figures(record.get("result"), lang)
        for hit in hits:
            if hit.kind != "quarter":
                return hit.value
    return None


def _source_pool(url: str, records: list[dict], lang: str) -> list[NumberSpan]:
    wanted = _norm_url(url)
    if wanted is None:
        return []
    hits: list[NumberSpan] = []
    for record in records:
        if str(record.get("kind") or "").lower() != "source":
            continue
        if _norm_url(str(record.get("url") or "")) != wanted:
            continue
        hits.extend(extract_numbers(str(record.get("text") or ""), lang))
    return hits


def island_host(url: str) -> str | None:
    """Return the host when it is island.is or a subdomain of it.

    ``island.is.evil.com`` is not such a host: the suffix must be the dot
    plus ``island.is``, or the host must be exactly ``island.is``.
    """

    if not isinstance(url, str):
        return None
    raw = url.strip()
    if not raw or any(ch in raw for ch in "\\\x00\t\n\r "):
        return None
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    # userinfo is not the host. ``https://evil.com@island.is/`` must not pass.
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        return None
    host = parsed.hostname
    if not host:
        return None
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    host = host.lower().rstrip(".")
    if host == "island.is" or host.endswith(".island.is"):
        return host
    return None


def _norm_url(url: str) -> str | None:
    host = island_host(url)
    if host is None:
        return None
    parsed = urlparse(url.strip())
    path = parsed.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    scheme = parsed.scheme.lower()
    normalized = f"{scheme}://{host}{path}"
    if parsed.query:
        normalized += "?" + parsed.query
    return normalized


def _label(meta: dict) -> str:
    if meta.get("label"):
        return str(meta["label"])
    if _lang(meta.get("lang") or meta.get("language")) == "is":
        return LABEL_IS
    return LABEL_EN


def _fingerprint(meta: dict) -> str:
    supplied = meta.get("answer_hash")
    if supplied:
        return str(supplied)
    answer = meta.get("answer", meta.get("verified_answer", ""))
    if not isinstance(answer, str):
        answer = json.dumps(answer, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(answer.encode("utf-8")).hexdigest()


def _require_meta(meta: dict) -> None:
    if not isinstance(meta, dict) or not meta.get("model") or not meta.get("timestamp"):
        raise ElabGuardError("model and timestamp are required")


def _key() -> str:
    key = os.environ.get("GRUND_ELAB_HMAC_KEY")
    if not key:
        raise ElabGuardError("GRUND_ELAB_HMAC_KEY is not set")
    return key


def _mac(meta: dict) -> str:
    _require_meta(meta)
    message = f"{_fingerprint(meta)}|{meta['model']}|{meta['timestamp']}"
    return hmac.new(_key().encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def _payload(meta: dict) -> str:
    mac = _mac(meta)
    return f"v1|{mac[:8]}|{mac}"


def _zw_encode(payload: str) -> str:
    bits = "".join(f"{byte:08b}" for byte in payload.encode("ascii"))
    body = "".join(_ZW0 if bit == "0" else _ZW1 for bit in bits)
    return _ZW_START + body + _ZW_END


def _zw_decode_all(text: str) -> list[str]:
    found = []
    offset = 0
    while True:
        start = text.find(_ZW_START, offset)
        if start < 0:
            break
        end = text.find(_ZW_END, start + len(_ZW_START))
        if end < 0:
            break
        body = text[start + len(_ZW_START) : end]
        offset = end + len(_ZW_END)
        if not body or len(body) % 8 or any(ch not in (_ZW0, _ZW1) for ch in body):
            continue
        raw = bytearray()
        for offset in range(0, len(body), 8):
            bits = "".join("0" if ch == _ZW0 else "1" for ch in body[offset : offset + 8])
            raw.append(int(bits, 2))
        try:
            found.append(raw.decode("ascii"))
        except UnicodeDecodeError:
            continue
    return found


def _visible(text: str) -> str:
    return "".join(ch for ch in text if ch not in _ZW_HIDDEN).strip()
