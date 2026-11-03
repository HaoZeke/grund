"""Parse a question, then call PxWeb. The ranker runs only as a fallback.

A table is a candidate when every filter maps to a value code and every
other variable is a total or can be left out. The operation is applied in
code to the cells that came back. Up to four mapped tables are tried. A
refusal names the reason and the candidate links.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from grund_lang.fold import STOP, fold
from grund_lang.request import ParseError, parse_request, validate_request

_DATABASES = ("Atvinnuvegir", "Efnahagur", "Ibuar", "Samfelag", "Umhverfi")
_TOTALS = {"total", "alls", "samtals", "heild", "all", "allt", "oll", "heildarafli"}
_MAX_TABLES = 4


def web_url(api_url: str) -> str:
    return api_url.replace("/api/v1/", "/pxweb/")


def answer(
    question: str,
    store: "MetaStore",
    client,
    *,
    ranker=None,
    live: bool = True,
    mode: str = "hybrid",
) -> dict:
    """Run parse-then-tools. `ranker` is `retrieve` and is used only on failure."""
    started = time.perf_counter()
    timings = {"parse": 0.0, "search": 0.0, "map": 0.0, "post": 0.0, "total": 0.0}
    t0 = time.perf_counter()
    try:
        request = parse_request(question)
        errors = validate_request({key: request[key] for key in ("measure", "filters", "period", "op", "unit_hint")})
    except ParseError as exc:
        errors = [str(exc)]
        request = None
    timings["parse"] = time.perf_counter() - t0
    if errors or request is None:
        result = _fallback(question, ranker, client, store, "parse failed: " + "; ".join(errors or ["empty"]), None, timings)
        result["latency"] = _finish(timings, started)
        return result

    t1 = time.perf_counter()
    found = _candidates(store, request, ranker, question, client if live else None, mode)
    timings["search"] = time.perf_counter() - t1
    language = request.get("_language") or "en"
    tried: list[dict] = []
    unmapped: list[dict] = []
    last_reason = "no table mapped every filter"
    for table_id, _score in found:
        if len(tried) >= _MAX_TABLES:
            break
        edition = store.edition(table_id, language)
        if edition is None:
            continue
        t2 = time.perf_counter()
        mapped = map_request(edition, request)
        timings["map"] += time.perf_counter() - t2
        link = {"table_id": table_id, "api_url": edition.get("url") or "", "web_url": web_url(edition.get("url") or "")}
        if mapped is None:
            unmapped.append({**link, "reason": "filters did not map"})
            continue
        tried.append(link)
        t3 = time.perf_counter()
        payload = _post(client, edition.get("url") or "", mapped)
        timings["post"] += time.perf_counter() - t3
        claim = _claim_from_payload(table_id, edition, mapped, payload, request)
        if claim is None:
            last_reason = "the query returned no usable cells"
            continue
        blocked = rail_block(claim)
        if blocked:
            last_reason = blocked
            continue
        claim["latency"] = _finish(timings, started)
        claim["confidence"] = _confidence(found, table_id, request, store)
        claim["source"] = mode if mode in {"tools", "hybrid", "ranker"} else "tools"
        claim["request"] = {key: request[key] for key in ("measure", "filters", "period", "op", "unit_hint")}
        return claim

    if not tried:
        result = _fallback(question, ranker, client, store, last_reason, request, timings)
        result["candidates"] = unmapped + list(result.get("candidates") or [])
        result["latency"] = _finish(timings, started)
        return result
    result = _refuse(last_reason, unmapped + tried, request)
    result["source"] = mode if mode in {"tools", "hybrid", "ranker"} else "tools"
    result["latency"] = _finish(timings, started)
    return result


def rail_block(claim: dict) -> str | None:
    """A claim is blocked when the stated value is not the operation on the cells."""
    cells = claim.get("cells") or []
    if not cells:
        return "claim has no cells"
    for cell in cells:
        for field in ("table_id", "coords", "labels", "value", "api_url", "web_url", "retrieved_at"):
            if not cell.get(field) and cell.get(field) != 0:
                return f"cell missing {field}"
        if not _numeric(cell.get("value")):
            return "cell value is not a number"
    op = claim.get("op")
    try:
        expected = compute_op(op, [str(cell["value"]) for cell in cells])
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    if str(claim.get("value")) != expected:
        return "claim value is not the operation on the cited cells"
    return None


def compute_op(op: str, raws: list[str]) -> str:
    """The figure a claim may state. Inputs are the strings PxWeb returned."""
    from decimal import Decimal

    from grund.arithmetic import difference, share_percent, to_decimal, yoy_percent
    from grund.compute import _percent_string

    if op == "level":
        return _plain(raws[0])
    if op == "sum":
        total = sum((to_decimal(raw) for raw in raws), Decimal(0))
        return _plain(total)
    if op == "change":
        if len(raws) < 2:
            raise ValueError("a change needs two cells")
        return _plain(difference(raws[-1], raws[0]))
    if op == "pct_change":
        if len(raws) < 2:
            raise ValueError("a percent change needs two cells")
        return _percent_string(yoy_percent(raws[-1], raws[0]))
    if op == "share":
        if len(raws) < 2:
            raise ValueError("a share needs the part and the total")
        return _percent_string(share_percent(raws[0], raws[1]))
    if op == "compare":
        return _plain(raws[0])
    raise ValueError(f"unknown op {op}")


def map_request(edition: dict, request: dict) -> dict[str, list[str]] | None:
    """Variable code to value codes, or None when the table cannot answer."""
    variables = edition.get("variables") or []
    chosen: dict[str, list[str]] = {}
    used: set[str] = set()
    for _dimension, values in (request.get("filters") or {}).items():
        for said in values:
            hit = _best_filter(variables, said, used)
            if hit is None:
                return None
            code, value_code = hit
            chosen.setdefault(code, [])
            if value_code not in chosen[code]:
                chosen[code].append(value_code)
            used.add(code)
    if request.get("op") == "share":
        if not _attach_share_total(variables, chosen):
            return None
    time_var = _time_variable(edition)
    if time_var is not None:
        codes = _time_codes(time_var, request.get("period") or {})
        if not codes:
            return None
        chosen[time_var["code"]] = codes
        used.add(time_var["code"])
    for variable in variables:
        if variable["code"] in used:
            continue
        if variable.get("elimination"):
            continue
        # A named row beats the total, including "1. Flug" for "flugi".
        # Several equally specific rows is not a licence to answer with the total.
        question = str(request.get("_question") or "")
        named = match_value_codes(variable.get("values") or [], question, str(edition.get("title") or ""))
        if len(named) > 1:
            return None
        if len(named) == 1:
            chosen[variable["code"]] = [named[0]]
            continue
        # "Total - excluding public administration" is the row. Bare "Total"
        # is only the row when the question did not write a longer label.
        written = _written_label(variable, question)
        if written is not None:
            chosen[variable["code"]] = [written]
            continue
        total = _total_code(variable)
        if total is not None:
            chosen[variable["code"]] = [total]
            continue
        picked = _measure_code(variable, request)
        if picked is not None and len(variable.get("values") or []) <= 12:
            chosen[variable["code"]] = [picked]
            continue
        return None
    return _honour_named_values(
        variables,
        chosen,
        str(request.get("_question") or ""),
        str(edition.get("title") or ""),
    )


def _honour_named_values(
    variables: list[dict],
    chosen: dict[str, list[str]],
    question: str,
    title: str = "",
) -> dict[str, list[str]] | None:
    """A place the question names replaces the total. A table without that place cannot answer.

    A label that only repeats the table title is not a place. "Deposit taking
    corporations" is the table, not a borrower.
    """
    from grund.agree_hyb import enabled as agree_hyb
    from grund.agree_hyb import label_named, place_missing
    from grund_index.textutil import fold

    if not agree_hyb() or not question:
        return chosen
    if place_missing(question, variables):
        return None
    title_tokens = set(re.findall(r"[a-z0-9]+", fold(title)))
    for variable in variables:
        if variable.get("time"):
            continue
        named = []
        for code, label in variable.get("values") or []:
            if not label_named(str(label), question):
                continue
            label_tokens = [token for token in re.findall(r"[a-z0-9]+", fold(str(label))) if len(token) >= 4]
            if label_tokens and all(token in title_tokens for token in label_tokens):
                continue
            named.append(str(code))
        if not named:
            continue
        current = chosen.get(variable["code"]) or []
        if any(code in named for code in current):
            continue
        chosen[variable["code"]] = [named[0]]
    return chosen


class MetaStore:
    """Offline metadata index, optionally joined with the live database search."""

    def __init__(self, tables_path: str, catalogue_path: str | None = None) -> None:
        import gzip
        import json
        from pathlib import Path

        self.by_id: dict[str, dict[str, dict]] = {}
        opener = gzip.open if str(tables_path).endswith(".gz") else open
        with opener(tables_path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                table_id = str(row.get("id") or "").replace(".px", "")
                self.by_id.setdefault(table_id, {})[row.get("lang") or "en"] = row
        self._docs = []
        self._by_doc: dict[str, dict] = {}
        for table_id, editions in self.by_id.items():
            doc = _doc(table_id, editions)
            self._docs.append(doc)
            self._by_doc[doc["id"]] = doc

    def edition(self, table_id: str, language: str) -> dict | None:
        editions = self.by_id.get(table_id.replace(".px", ""))
        if not editions:
            return None
        return editions.get(language) or editions.get("en") or next(iter(editions.values()))

    def search(self, request: dict, client=None) -> list[tuple[str, float]]:
        scored = {}
        for doc in self._docs:
            score = measure_score(doc, request)
            if score <= 0:
                continue
            scored[doc["id"]] = score
        # The shipped metadata index already names every table. A live
        # database search is only a fallback when that index did not load.
        if client is not None and not self.by_id:
            for table_id, live_score in _live_ids(
                client, request.get("_language") or "en", measure_terms(request)
            ):
                scored[table_id] = scored.get(table_id, 0.0) + live_score
        return sorted(scored.items(), key=lambda item: item[1], reverse=True)[:8]

    def score_ids(self, table_ids: list[str], request: dict) -> list[tuple[str, float]]:
        """Order a given shortlist by measure and unit match. Zero scores drop out."""
        scored = []
        for table_id in table_ids:
            doc = self._by_doc.get(table_id.replace(".px", ""))
            if doc is None:
                continue
            score = measure_score(doc, request)
            if score > 0:
                scored.append((doc["id"], score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored


def _doc(table_id: str, editions: dict[str, dict]) -> dict:
    title: set[str] = set()
    path: set[str] = set()
    variables: set[str] = set()
    labels: set[str] = set()
    overview = False
    historical = False
    updated = ""
    for edition in editions.values():
        title.update(_terms(edition.get("title") or ""))
        path.update(_terms(" ".join(edition.get("path_texts") or [])))
        blob = fold(" ".join(edition.get("path_texts") or []))
        updated = max(updated, edition.get("updated") or "")
        if "yfirlit" in blob or "overview" in blob:
            overview = True
        if any(mark in blob for mark in ("eldra", "soguleg", "earlier", "previous")):
            historical = True
        for variable in edition.get("variables") or []:
            variables.update(_terms(variable.get("text") or ""))
            variables.update(_terms(variable.get("code") or ""))
            for _code, label in variable.get("values") or []:
                labels.update(_terms(str(label)))
    return {
        "id": table_id,
        "title": title,
        "path": path,
        "variables": variables,
        "labels": labels,
        "overview": overview,
        "historical": historical,
        "updated": updated,
    }


_MEASURE_SKIP = STOP | {
    "iceland", "island", "islandi", "published", "skrad", "people", "person",
    "lived", "bjuggu", "ibuar", "figure", "figures",
}


def measure_terms(request: dict) -> list[str]:
    """Content words of the measure, without place-holder words such as Iceland."""
    return [term for term in _terms(request.get("measure") or "") if term not in _MEASURE_SKIP]


def measure_score(doc: dict, request: dict) -> float:
    """How well the measure and the unit hint meet a variable or a unit label.

    Topic words that only appear as a geography label do not count. A table
    with no content hit scores zero and is not a candidate.
    """
    terms = measure_terms(request)
    if not terms:
        return 0.0
    title_hits = sum(1 for term in terms if term in doc["title"] or term in doc["path"])
    variable_hits = sum(1 for term in terms if term in doc["variables"])
    if title_hits + variable_hits == 0:
        return 0.0
    unit_terms = [term for term in _terms(request.get("unit_hint") or "") if term not in _MEASURE_SKIP]
    unit_hits = sum(
        1 for term in unit_terms
        if term in doc["labels"] or term in doc["variables"] or term in doc["title"]
    )
    score = 3.0 * title_hits + 4.0 * variable_hits + 2.0 * unit_hits
    if doc.get("overview") and title_hits:
        score += 0.5
    if doc.get("historical"):
        score *= 0.5
    # Same measure words: the later update is the current series. The bonus
    # is smaller than one extra content hit, so it only breaks ties.
    stamp = (doc.get("updated") or "")[:4]
    if stamp.isdigit():
        score += (int(stamp) - 2000) * 0.01
    return score


def _terms(text: str) -> list[str]:
    folded = fold(text)
    return [token for token in folded.replace("-", " ").split() if len(token) > 2 and token not in STOP and not token.isdigit()]


def _live_ids(client, language: str, terms: list[str]) -> list[tuple[str, float]]:
    if not terms:
        return []
    query = urllib.parse.quote(" ".join(terms[:5]))
    root = "pxen" if language == "en" else "pxis"
    found: dict[str, float] = {}
    for database in _DATABASES:
        url = f"https://px.hagstofa.is/{root}/api/v1/{language}/{database}?query={query}"
        try:
            payload = client.get_json(url)
        except Exception:
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            table_id = str(item["id"]).replace(".px", "")
            found[table_id] = max(found.get(table_id, 0.0), float(item.get("score") or 0.0) * 5.0)
    return list(found.items())


_VALUE_WORDS = {
    "women": {"female", "females", "woman", "women", "kona", "konur", "stulka", "stulkur", "girl", "girls"},
    "woman": {"female", "females", "woman", "women", "kona", "konur"},
    "konur": {"female", "females", "kona", "konur", "stulka", "stulkur"},
    "men": {"male", "males", "man", "men", "karl", "karlar", "drengur", "drengir", "boy", "boys"},
    "karlar": {"male", "males", "karl", "karlar", "drengur", "drengir"},
    "foreigners": {"foreigner", "foreigners", "utlendingur", "utlendingar", "utlending", "erlendur"},
    "utlendingar": {"foreigner", "foreigners", "utlendingur", "utlendingar", "utlending"},
}


def _best_filter(variables: list[dict], said: str, used: set[str]) -> tuple[str, str] | None:
    needle = set(_terms(said))
    folded = fold(said)
    synonyms = set()
    for key, words in _VALUE_WORDS.items():
        if key == folded or key in needle:
            synonyms |= words
    best: tuple[float, str, str] | None = None
    for variable in variables:
        if variable["code"] in used or variable.get("time"):
            continue
        for code, label in variable.get("values") or []:
            label_fold = fold(str(label))
            label_terms = set(_terms(str(label)))
            score = 0.0
            if label_fold == folded:
                score = 10.0
            elif folded and (folded in label_fold or label_fold in folded) and len(folded) >= 4:
                score = 7.0
            elif synonyms and (label_terms & synonyms or any(word in label_fold for word in synonyms)):
                score = 8.0
            else:
                score = 2.0 * len(needle & label_terms)
            if score >= 6.0 and (best is None or score > best[0]):
                best = (score, variable["code"], str(code))
    if best is None:
        return None
    return best[1], best[2]


def _attach_share_total(variables: list[dict], chosen: dict[str, list[str]]) -> bool:
    for variable in variables:
        codes = chosen.get(variable["code"])
        if not codes:
            continue
        total = _total_code(variable)
        if total is None:
            continue
        labels = {str(code): fold(str(label)) for code, label in variable.get("values") or []}
        if any(labels.get(code) not in _TOTALS for code in codes):
            if total not in codes:
                codes.append(total)
            return True
    return False


# "1. Flug" and "01.1 Food" are list indexes. "30 years" is the row name.
_LIST_NUMBER = re.compile(r"^(?:\d+\.)+\d*\s+|^\d+\.\s+")
_GENERIC_ROW = {
    "year", "years", "old", "aged", "ara", "arid", "ari", "ars", "ar",
    "total", "totals", "alls", "samtals", "all", "heild",
    "index", "rate", "number", "percent", "percentage", "hlutfall", "prosent",
}
_CASE_ENDINGS = (
    "inum", "unum", "anna", "urnar", "arnar", "inni",
    "um", "ar", "ir", "ur", "inn", "an", "num", "i", "a", "u", "s",
)


def _case_forms(token: str) -> set[str]:
    """The token plus one short grammatical stem.

    ``flugi`` and ``flug`` are the same row. The stem has to be at least
    four letters, so a two-letter word is not stripped to nothing.
    """
    forms = {token}
    if len(token) < 5:
        return forms
    for suffix in _CASE_ENDINGS:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            forms.add(token[: -len(suffix)])
            break
    return forms


def _word_forms(text: str) -> set[str]:
    forms: set[str] = set()
    raw = text or ""
    icelandic = any(ch in raw.lower() for ch in "áéíóúýþæöð")
    lemmas = None
    try:
        from grund_index.textutil import icelandic_text, lemmas as lemma_fn

        icelandic = icelandic or icelandic_text(raw)
        lemmas = lemma_fn
    except Exception:
        lemmas = None
    for token in re.findall(r"[a-z0-9]+", fold(raw)):
        forms.add(token)
        forms.update(_case_forms(token))
        if lemmas is not None and len(token) >= 4:
            forms.update(lemmas(token, icelandic=icelandic))
    return forms


def stripped_label(label: str) -> str:
    """Drop a leading list number. ``1. Flug`` and ``01.1 Food`` keep the name."""
    return _LIST_NUMBER.sub("", fold(label or "").strip()).strip()


def match_value_codes(values, question: str, title: str = "") -> list[str]:
    """Non-total rows the question names, best match first when one is stricter.

    A tie at the top is returned in full. The caller then refuses a total
    instead of picking one of them.
    """
    asked = _word_forms(question)
    titled = _word_forms(title) if title else set()
    scored: list[tuple[int, str]] = []
    for code, label in values or []:
        plain = fold(str(label or "")).strip()
        if plain in _TOTALS or plain in _GENERIC_ROW:
            continue
        tokens = re.findall(r"[a-z0-9]+", stripped_label(str(label or "")))
        if not tokens:
            continue
        # "in Iceland" is the place. "16 years and older" is not the row 16.
        if plain in {"iceland", "island", "islandi"} and not re.search(
            r"\b(citizen|born|faed|rikisfang|origin|bakgrunn|upprun|thjoderni|islensk)\b",
            fold(question or ""),
        ):
            continue
        if re.search(r"\b(\d{1,3})\s+(?:years?|ara|ar)\s+(?:and|og)\s+(?:older|eldri)\b", fold(question or "")):
            if re.fullmatch(r"\d{1,3}(?:\s+years?|\s+ara|\s+ar)?", " ".join(tokens)):
                continue
        matched = 0
        blocked = False
        for token in tokens:
            if token.isdigit() and len(token) == 4:
                continue
            if token in _GENERIC_ROW:
                continue
            forms = _case_forms(token)
            if forms & titled:
                continue
            if token.isdigit():
                # "1 January" is a day. It does not name the age row "1 year".
                age_label = any(part in {"year", "years", "ara", "ar", "ari", "ars"} for part in tokens)
                named_age = re.search(
                    rf"\b{re.escape(token)}\s+(?:years?|ara|ar)\b|\baged\s+{re.escape(token)}\b",
                    fold(question or ""),
                )
                if age_label and not named_age:
                    continue
                if token in asked:
                    matched += 1
                else:
                    blocked = True
                continue
            if len(token) < 4:
                # "of" and "in" do not name a row. A one-word label such as
                # "air" still matches when it is the whole label.
                if len(tokens) == 1 and len(token) >= 3 and token in asked:
                    matched += 1
                continue
            if forms & asked or token in asked:
                matched += 1
            elif len(token) >= 4:
                blocked = True
        if matched and not blocked:
            scored.append((matched, str(code)))
    if not scored:
        return []
    best = max(item[0] for item in scored)
    return [code for count, code in scored if count == best]


def _written_label(variable: dict, question: str) -> str | None:
    """The longest value label that the question writes out in full."""
    folded_q = fold(question or "")
    if not folded_q:
        return None
    best: tuple[int, str] | None = None
    for code, label in variable.get("values") or []:
        plain = fold(str(label or ""))
        if len(plain) < 12 or plain not in folded_q:
            continue
        if best is None or len(plain) > best[0]:
            best = (len(plain), str(code))
    return None if best is None else best[1]


def _total_code(variable: dict) -> str | None:
    """The aggregate value, including labels the catalogue does not spell 'Total'.

    An exact total wins. Otherwise a label that starts with total and says
    all ("Total - all activities"), otherwise the first label that ends with
    "total" ("Long-term foreign debt, total"). "Total revenue" is a line in
    an account list, not the aggregate, so it does not match.
    """
    pairs = [(str(code), str(label)) for code, label in variable.get("values") or []]
    for code, label in pairs:
        if fold(label) in _TOTALS:
            return code
    for code, label in pairs:
        words = re.findall(r"[a-z]+", fold(label))
        if words and words[0] == "total" and "all" in words:
            return code
    for code, label in pairs:
        folded = fold(label).strip()
        if folded.endswith(" total"):
            return code
    return None


def _looks_like_time(variable: dict) -> bool:
    """A period variable. Some editions leave the time flag unset."""
    if variable.get("time"):
        return True
    values = variable.get("values") or []
    if not values:
        return False
    dated = sum(
        1
        for code, label in values
        if re.search(r"(?:18|19|20)\d{2}", f"{code} {label}")
    )
    if dated < max(1, int(0.8 * len(values))):
        return False
    name = fold(str(variable.get("text") or ""))
    if "birth" in name or "faeding" in name:
        return False
    return True


def _time_variable(edition: dict) -> dict | None:
    variables = edition.get("variables") or []
    flagged = next((variable for variable in variables if variable.get("time")), None)
    if flagged is not None:
        return flagged
    return next((variable for variable in variables if _looks_like_time(variable)), None)


def _measure_code(variable: dict, request: dict) -> str | None:
    hint = set(_terms(request.get("unit_hint") or "")) | set(_terms(request.get("measure") or ""))
    best: tuple[float, str] | None = None
    for code, label in variable.get("values") or []:
        folded = fold(str(label))
        if any(word in folded for word in ("change", "breyting", "percent", "hlutfall")):
            continue
        overlap = hint & set(_terms(str(label)))
        score = 2.0 * len(overlap)
        if folded in {"index", "visitala", "visitola"} and "index" in hint:
            score += 5.0
        if score > 0 and (best is None or score > best[0]):
            best = (score, str(code))
    if best:
        return best[1]
    values = variable.get("values") or []
    if len(values) == 1:
        return str(values[0][0])
    return None


def _time_codes(variable: dict, period: dict) -> list[str]:
    kind = period.get("kind")
    values = [(str(code), str(label)) for code, label in variable.get("values") or []]
    if kind == "latest":
        return [values[-1][0]] if values else []
    if kind == "range":
        start = (period.get("start") or {}).get("year")
        end = (period.get("end") or {}).get("year")
        codes = [_match_time(values, int(start)), _match_time(values, int(end))]
        return [code for code in codes if code]
    year = int(period.get("year"))
    month = period.get("month")
    quarter = period.get("quarter")
    if month:
        code = _match_time(values, year, month=int(month))
        return [code] if code else []
    if quarter:
        code = _match_time(values, year, quarter=int(quarter))
        return [code] if code else []
    code = _match_time(values, year)
    return [code] if code else []


def _match_time(values: list[tuple[str, str]], year: int, month: int | None = None, quarter: int | None = None) -> str | None:
    if month:
        token = f"{year}M{month:02d}"
        for code, label in values:
            if token in code or token in label:
                return code
    if quarter:
        token = f"{year}Q{quarter}"
        for code, label in values:
            if token in code.upper() or token in label.upper():
                return code
    for code, label in values:
        if code == str(year) or label == str(year):
            return code
    return None


_POSTS: dict[str, Any] = {}


def _post(client, url: str, chosen: dict[str, list[str]]) -> Any:
    if client is None or not url:
        return None
    body = {
        "query": [
            {"code": code, "selection": {"filter": "item", "values": values}}
            for code, values in chosen.items()
            if values
        ],
        "response": {"format": "json"},
    }
    key = url + "\n" + json.dumps(body, ensure_ascii=False, sort_keys=True)
    if key in _POSTS:
        return _POSTS[key]
    try:
        payload = client.post_json(url, body)
    except Exception:
        return None
    _POSTS[key] = payload
    return payload


def _claim_from_payload(table_id: str, edition: dict, chosen: dict[str, list[str]], payload: Any, request: dict) -> dict | None:
    rows = _rows(payload)
    if not rows:
        return None
    op = request.get("op") or "level"
    if op == "share" and len(rows) < 2:
        return None
    if op in {"change", "pct_change", "sum"} and len(rows) < 2 and op != "sum":
        return None
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    api = edition.get("url") or ""
    cells = []
    for key, raw, columns in rows:
        coords = {}
        labels = {}
        codes = columns or list(chosen)
        for index, code in enumerate(codes):
            if index >= len(key):
                break
            coords[code] = key[index]
            labels[code] = _label_for(edition, code, key[index])
        cells.append({
            "table_id": table_id,
            "coords": coords,
            "labels": labels,
            "value": raw,
            "api_url": api,
            "web_url": web_url(api),
            "retrieved_at": now,
        })
    if op == "share":
        cells = _order_share(cells, edition, chosen)
    periods = _attach_periods(cells, edition)
    try:
        value = compute_op(op, [cell["value"] for cell in cells])
    except Exception:
        return None
    claim = {
        "value": value,
        "op": op,
        "unit": request.get("unit_hint") or "",
        "cells": cells,
        "period": _claim_period(periods),
        "labels": {key: label for cell in cells for key, label in (cell.get("labels") or {}).items()},
        "refused": False,
        "reason": None,
        "candidates": [],
        "confidence": 0.0,
        "source": "tools",
    }
    if op == "share" and len(cells) >= 2:
        claim["inputs"] = [cells[0]["value"], cells[1]["value"]]
    return claim


def _attach_periods(cells: list[dict], edition: dict) -> list[str]:
    """Put the time code on `period`, which is where the cell rail reads a year.

    Labels use the variable's text and leave the time variable out, matching
    the claim the ranker already passes through that rail. A change with no
    `period` cannot be recomputed, and the rail then refuses the answer.
    """
    variable = _time_variable(edition)
    latest = ""
    if variable:
        values = variable.get("values") or []
        if values:
            latest = str(values[-1][0])
    periods: list[str] = []
    for cell in cells:
        period = ""
        if variable:
            period = str((cell.get("coords") or {}).get(variable["code"]) or "")
        cell["period"] = period
        if latest:
            cell["latest_period"] = latest
        labels: dict[str, str] = {}
        for code, value_code in (cell.get("coords") or {}).items():
            owner = next((item for item in edition.get("variables") or [] if item.get("code") == code), None)
            if owner is not None and (owner.get("time") or owner is variable):
                continue
            name = (owner.get("text") if owner else None) or code
            labels[str(name)] = _label_for(edition, code, value_code)
        cell["labels"] = labels
        if period:
            periods.append(period)
    return periods


def _claim_period(periods: list[str]) -> str:
    if not periods:
        return ""
    if len(set(periods)) == 1:
        return periods[0]
    return f"{periods[0]} to {periods[-1]}"


def _order_share(cells: list[dict], edition: dict, chosen: dict[str, list[str]]) -> list[dict]:
    for code, values in chosen.items():
        if len(values) < 2:
            continue
        variable = next((item for item in edition.get("variables") or [] if item.get("code") == code), None)
        total = _total_code(variable) if variable else None
        if total is None:
            continue
        return sorted(cells, key=lambda cell: 1 if cell["coords"].get(code) == total else 0)
    return cells


def _rows(payload: Any) -> list[tuple[list[str], str, list[str]]]:
    if not isinstance(payload, dict):
        return []
    columns = [
        str(column.get("code"))
        for column in payload.get("columns") or []
        if column.get("code") and column.get("type") != "c"
    ]
    found = []
    for item in payload.get("data") or []:
        raw = (item.get("values") or [None])[0]
        if raw in (None, "", ".", "..", "..."):
            continue
        if not _numeric(raw):
            continue
        found.append(([str(part) for part in item.get("key") or []], str(raw), columns))
    return found


def _label_for(edition: dict, code: str, value_code: str) -> str:
    for variable in edition.get("variables") or []:
        if variable.get("code") != code:
            continue
        for item, label in variable.get("values") or []:
            if str(item) == value_code:
                return str(label)
    return value_code


def _numeric(raw: Any) -> bool:
    try:
        from grund.arithmetic import to_decimal

        to_decimal(str(raw))
        return True
    except Exception:
        return False


def _plain(raw: Any) -> str:
    from decimal import Decimal

    from grund.arithmetic import to_decimal

    value = raw if isinstance(raw, Decimal) else to_decimal(str(raw))
    if value == value.to_integral():
        return str(value.to_integral())
    return format(value.normalize(), "f")


def _candidates(store: MetaStore, request: dict, ranker, question: str, client, mode: str) -> list[tuple[str, float]]:
    if mode == "ranker":
        if ranker is None:
            return []
        return [(candidate.table_id, float(candidate.score)) for candidate in ranker(question, k=4)]
    if mode == "hybrid":
        if ranker is None:
            return store.search(request, client)
        identifiers = [candidate.table_id for candidate in ranker(question, k=20)]
        return store.score_ids(identifiers, request)
    return store.search(request, client)


def _confidence(found: list[tuple[str, float]], table_id: str, request: dict, store: MetaStore) -> float:
    """Chance the cell is the gold value, calibrated on dev-short-tune.

    The raw score is half the margin over the next candidate and half the
    share of measure words found on the table. `_calibrated` maps that raw
    score to the pooled accuracy observed on the tune set.
    """
    top = next((score for ident, score in found if ident == table_id), 0.0)
    rest = [score for ident, score in found if ident != table_id]
    second = max(rest) if rest else 0.0
    margin = (top - second) / top if top else 0.0
    terms = measure_terms(request)
    doc = store._by_doc.get(table_id.replace(".px", ""))
    if not terms or doc is None:
        coverage = 0.0
    else:
        hits = sum(1 for term in terms if term in doc["title"] or term in doc["path"] or term in doc["variables"])
        coverage = hits / len(terms)
    raw = max(0.0, min(1.0, 0.5 * max(margin, 0.0) + 0.5 * coverage))
    return round(_calibrated(raw), 4)


# Empirical accuracy of the raw score on dev-short-tune, pooled so it never
# falls as the score rises. A threshold on this value is a coverage/accuracy cut.
# Raw score edges and the pooled accuracy of dev-short-tune below that edge.
# 0.40 to 0.80 was not higher than 0.20 to 0.40, so those bins are one step.
_CALIBRATION: tuple[tuple[float, float], ...] = (
    (0.20, 0.048),
    (0.80, 0.132),
    (1.01, 0.50),
)


def _calibrated(raw: float) -> float:
    # Identity until the tune bins below are filled in. The edges are the
    # pooled accuracy of this raw score on dev-short-tune.
    if not _CALIBRATION:
        return raw
    for edge, accuracy in _CALIBRATION:
        if raw < edge:
            return accuracy
    return _CALIBRATION[-1][1]


def _refuse(reason: str, links: list[dict], request: dict | None) -> dict:
    return {
        "value": None,
        "op": (request or {}).get("op"),
        "unit": (request or {}).get("unit_hint") or "",
        "cells": [],
        "refused": True,
        "reason": reason,
        "candidates": links,
        "confidence": 0.0,
        "source": "tools",
    }


def _fallback(question: str, ranker, client, store: MetaStore, reason: str, request: dict | None, timings: dict) -> dict:
    if ranker is None:
        return _refuse(reason, [], request)
    try:
        candidates = ranker(question, k=4)
    except Exception as exc:  # noqa: BLE001
        return _refuse(f"{reason}; ranker failed: {exc}", [], request)
    links = []
    language = (request or {}).get("_language") or "en"
    for candidate in candidates[:_MAX_TABLES]:
        edition = store.edition(candidate.table_id, language)
        url = (edition or {}).get("url") or ""
        links.append({"table_id": candidate.table_id, "api_url": url, "web_url": web_url(url)})
        if request is None or edition is None:
            continue
        mapped = map_request(edition, request)
        if mapped is None:
            continue
        t3 = time.perf_counter()
        payload = _post(client, url, mapped)
        timings["post"] += time.perf_counter() - t3
        claim = _claim_from_payload(candidate.table_id, edition, mapped, payload, request)
        if claim is None or rail_block(claim):
            continue
        claim["source"] = "ranker"
        claim["confidence"] = 0.0
        claim["request"] = {key: request[key] for key in ("measure", "filters", "period", "op", "unit_hint")}
        return claim
    result = _refuse(reason + "; ranker fallback", links, request)
    result["source"] = "ranker"
    return result


def _finish(timings: dict, started: float) -> dict:
    timings["total"] = time.perf_counter() - started
    return {key: round(value, 4) for key, value in timings.items()}
