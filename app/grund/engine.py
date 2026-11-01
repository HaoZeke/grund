"""Ask a question, fetch the cells, compute, then let the rails look."""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from grund.answer import refusal, render
from grund.compound import combine_answers, split_question
from grund.arithmetic import ArithmeticError, format_stat
from grund.bind import Binding, bind
from grund.compute import allowed_numbers, compute, extract_rows, footnotes, release_flags
from grund.langbind import binding_from_values
from grund.llm import ChatClient, parse_json_object
from grund.parse import ParsedQuestion, parse_question
from grund.planner import (
    binding_from_model,
    confidence_band,
    messages_for,
    model_messages,
    query_schema,
    selection_signature,
    shortlist,
    use_model_selections,
)
from grund.retrieve import ListingRetriever, listing_path
from grund.scope import clearly_out_of_scope
from grund.validator import ValidationError, query_body, validate
from grund_index.catalogue import Catalogue, Hit
from grund_index.client import PxWebClient, PxWebError
from grund_index.model import Edition, Table
from grund_index.textutil import fold, tokens
from grund_rails.engine import RailEngine, default_engine
from grund_rails.plan import Plan, PlanError

def _looks_like_time(variable: str, code: str) -> bool:
    name = fold(variable)
    if name in {"ar", "year", "manudur", "month", "timabil", "quarter", "arsfjordungur"}:
        return True
    return bool(re.fullmatch(r"(?:19|20)\d{2}(?:[MQ]\d{1,2})?", str(code), flags=re.I))


def _declared_measure(question: str, operation: str) -> str:
    """The measure the claim answers. A typed request can override this later."""
    if operation == "share":
        return "share"
    from grund_rails.cell_claim import infer_measure

    return infer_measure(question)


def _breakdown_title(result: dict) -> bool:
    """A cross-tab title. The same figure on a key-figures table is the headline."""
    claims = result.get("claims") or []
    title = ""
    if claims:
        cells = claims[0].get("cells") or []
        if cells:
            title = str(cells[0].get("title") or "")
    folded = fold(title)
    return " by " in f" {folded} " or " eftir " in f" {folded} "


def _latest_period(edition: Edition, binding: Binding | None = None) -> str:
    variable = edition.time_variable()
    if variable is None or not variable.values:
        return ""
    code, _label = variable.values[-1]
    notes = " ".join(binding.notes) if binding is not None else ""
    # The last code can be empty. The cell we kept is then the latest figure.
    if binding is not None and binding.time_codes and (
        "had no figure" in notes or "bind2-latest" in notes
    ):
        return str(binding.time_codes[-1])
    return str(code)


class IndexOffline(RuntimeError):
    """The value-label index is not loaded. Catalogue search is not a substitute."""


def _index_offline(path, detail: str) -> IndexOffline:
    return IndexOffline(
        "value-label index is missing or unreadable at "
        f"{path}. The default path runs the catalogue ranker and hybrid "
        "together, and hybrid does not run without this index. Catalogue "
        "search is not a substitute, and a missing index is not a quiet refusal.\n"
        f"{detail.strip()}\n"
        "Build it, then start again:\n"
        "  sh lang/fetch-index.sh\n"
        "That fetches the e5 checkpoint, then hf-mirror, then builds a "
        "chargram index if neither host answers. GRUND_LANG_INDEX overrides the path."
    )


def _jsonish(value):
    if isinstance(value, (list, tuple)):
        return [_jsonish(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonish(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _path_card(result: dict) -> dict:
    """Table, figure, and cell identity. Not the question, and not the sentence."""
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    cells = []
    for cell in source.get("cells") or []:
        if isinstance(cell, dict):
            cells.append({"key": _jsonish(cell.get("key")), "value": cell.get("value")})
    if not cells:
        for claim in result.get("claims") or []:
            if not isinstance(claim, dict):
                continue
            for cell in claim.get("cells") or []:
                if not isinstance(cell, dict):
                    continue
                cells.append(
                    {
                        "table_id": cell.get("table_id"),
                        "period": cell.get("period"),
                        "value": cell.get("value"),
                        "coords": _jsonish(cell.get("coords")),
                    }
                )
    return {
        "refused": bool(result.get("refused")) or result.get("value") in (None, ""),
        "value": result.get("value"),
        "value_display": result.get("value_display"),
        "table_id": result.get("table_id"),
        "detail": result.get("detail"),
        "cells": cells,
        "query": _jsonish(source.get("query")),
    }


def _path_pair(left: dict, right: dict) -> dict:
    return {"left": _path_card(left), "right": _path_card(right)}


def _rc1_on() -> bool:
    """Keep the one path that matched the question. Off unless ``GRUND_RC1`` is set."""
    return os.environ.get("GRUND_RC1", "").strip().lower() in {"1", "on", "true", "yes"}


def _asks_constant(question: str) -> bool:
    asked = fold(question)
    if any(phrase in asked for phrase in ("constant price", "fast verdlag", "fostu verd", "a fostu")):
        return True
    return re.search(r"\b(real|raun)\b", asked) is not None


def _result_blob(result: dict) -> str:
    parts: list[str] = []
    for claim in result.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            parts.append(str(cell.get("title") or ""))
            parts.append(str(cell.get("path") or ""))
            labels = cell.get("labels") or {}
            if isinstance(labels, dict):
                parts.extend(str(value) for value in labels.values())
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    parts.append(str(source.get("title") or ""))
    return fold(" ".join(parts))


def _constant_price_result(result: dict) -> bool:
    title = _result_blob(result)
    return any(phrase in title for phrase in ("constant price", "fast verdlag", "fostu verd"))


def _rc3_on() -> bool:
    """Trust the path whose cell label the question names. Off unless ``GRUND_RC3`` is set."""
    return os.environ.get("GRUND_RC3", "").strip().lower() in {"1", "on", "true", "yes"}


_RC3_TOTAL = {
    "total", "alls", "all", "samtals", "heild", "allt", "allir", "allar", "allur",
    "oll", "whole", "iceland", "island", "landid",
}
_RC3_GENERIC = {
    "visitala", "index", "fjoldi", "number", "percent", "percentage", "prosent",
    "hlutfall", "tonnes", "tonn", "rate", "value of index",
}


def _rc3_labels(result: dict) -> list[str]:
    found: list[str] = []
    for claim in result.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            labels = cell.get("labels") or {}
            if isinstance(labels, dict):
                found.extend(str(value) for value in labels.values())
            elif isinstance(labels, list):
                for item in labels:
                    if isinstance(item, dict):
                        found.append(str(item.get("label") or ""))
    return found


def _rc3_phrases(question: str, result: dict) -> list[str]:
    """Row labels the question names after its title clause, not the table title itself."""
    asked = fold(question or "")
    comma = asked.find(",")
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    title = fold(str(source.get("title") or ""))
    hits: list[str] = []
    for label in _rc3_labels(result):
        text = fold(label)
        if not text or text in _RC3_TOTAL or text in _RC3_GENERIC:
            continue
        if text.startswith("total") or text.startswith("alls"):
            continue
        if re.fullmatch(r"(?:19|20)\d{2}.*", text):
            continue
        if text in title or text not in asked:
            continue
        at = asked.find(text)
        if comma >= 0:
            if at < comma or len(text) < 8:
                continue
        elif len(text) < 12:
            continue
        hits.append(text)
    return hits


def _stated_path(result: dict) -> bool:
    return bool(result) and not result.get("refused") and result.get("value") not in (None, "")


def _same_table(left: dict, right: dict) -> bool:
    return str(left.get("table_id") or "").removesuffix(".px") == str(right.get("table_id") or "").removesuffix(".px") and bool(left.get("table_id"))


def _rc3_choice(question: str, ranker: dict, hybrid: dict) -> str | None:
    """The path whose row label the question names, when both used one table."""
    from grund.compound import split_question

    if split_question(question) is not None:
        return None
    if not (_stated_path(ranker) and _stated_path(hybrid) and _same_table(ranker, hybrid)):
        return None
    ranker_hits = _rc3_phrases(question, ranker)
    hybrid_hits = _rc3_phrases(question, hybrid)
    if ranker_hits and not hybrid_hits:
        return "ranker"
    if hybrid_hits and not ranker_hits:
        return "hybrid"
    return None


def _change_kept(kept: dict, other_match: bool, other: dict) -> bool:
    """The kept path computed the change. The other path cited one level."""
    if other_match or kept.get("refused") or kept.get("value") in (None, ""):
        return False
    if str(kept.get("operation") or "") not in {"difference", "change", "yoy_pct", "pct_change"}:
        return False
    reasons = [str(other.get("detail") or "")]
    for rail in other.get("rails") or []:
        if isinstance(rail, dict) and rail.get("reason"):
            reasons.append(str(rail["reason"]))
    return any("a change was asked and the cell is one level" in reason for reason in reasons)


def _mark_sole(result: dict, sole: bool) -> dict:
    if not sole:
        return result
    marked = dict(result)
    source = dict(marked.get("source") or {})
    source["sole_match"] = True
    marked["source"] = source
    return marked


def _table_preference(catalogue, frame, result: dict) -> int:
    stem = str(result.get("table_id") or "").removesuffix(".px")
    if not stem or catalogue is None:
        return 0
    table = catalogue.by_id.get(stem + ".px") or catalogue.by_id.get(stem)
    if table is None:
        return 0
    return frame.preference(table)


def _paths_agreed(result: dict, source: dict) -> bool:
    """Both answer paths cited one table and one figure.

    The index is a third vote in the agreement feature. When the frame has
    already made the two paths name the same cell, that vote is not a reason
    to withhold the figure.
    """
    if source.get("other_refused"):
        return False
    left = str(result.get("table_id") or "").removesuffix(".px")
    right = str(source.get("other_table") or "").removesuffix(".px")
    if not left or left != right:
        return False
    try:
        a = float(result.get("value"))
        b = float(source.get("other_value"))
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


def _sexdiff_agreed(chosen: dict, other: dict) -> bool:
    """Both paths stated the same recomputed sex gap on the same table."""
    formulas = {"men - women", "women - men"}

    def formula(result: dict) -> str:
        claims = result.get("claims") or []
        if not claims or not isinstance(claims[0], dict):
            return ""
        return str(claims[0].get("formula") or "")

    left, right = formula(chosen), formula(other)
    if not left or left not in formulas or left != right:
        return False
    if chosen.get("value") in (None, "") or other.get("value") in (None, ""):
        return False
    if str(chosen.get("table_id") or "").removesuffix(".px") != str(other.get("table_id") or "").removesuffix(".px"):
        return False
    try:
        a = float(chosen["value"])
        b = float(other["value"])
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= 1e-6 * max(1.0, abs(a))


def _guard_verdict(question: str, parsed: ParsedQuestion, produced: dict) -> dict:
    """Cell-claim rail. An unchecked result stops the process.

    Turning ``certain: false`` into a block used to refuse every question
    on a machine without Ruby. That state is a startup failure instead.
    """
    from grund_rails.vangrail_client import RailOffline, check_output

    context = _vangrail_context(question, parsed, produced)
    produced["claims"] = context["claims"]
    verdict = check_output(produced["prose"], question, context)
    if verdict.get("certain") is False:
        raise RailOffline(
            "checker offline: the cell-claim rail returned an unchecked pass. "
            "Grund will not refuse this question in its place. "
            "Start script/grund_guard_server.rb, or export GRUND_RAIL=python."
        )
    return verdict


def _vangrail_context(question: str, parsed: ParsedQuestion, produced: dict) -> dict:
    binding = produced["binding"]
    edition = produced["edition"]
    table = produced["table"]
    calculated = produced["calculated"]
    retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    derived = calculated.get("derived") or {}
    op = "share" if binding.operation == "share" else binding.operation
    value = derived.get("value") if derived.get("value") not in (None, "") else calculated.get("primary_raw")
    display = format_stat(str(value), parsed.language)
    cells = []
    for row in calculated["rows"]:
        labels = {}
        roles = {}
        coords = {}
        period = ""
        for label in row.get("labels") or []:
            code = str(label.get("code") or "")
            variable = str(label.get("variable") or "")
            text = str(label.get("label") or label.get("variable_text") or code)
            name = str(label.get("variable_text") or variable or code)
            coords[variable or name] = code
            labels[name] = text
            if _looks_like_time(name, code) or _looks_like_time(variable, code):
                roles[name] = "time"
                period = code or text
            elif fold(text) in {"total", "alls", "samtals", "all", "index"}:
                roles[name] = "total"
            else:
                roles[name] = "subgroup"
        cells.append(
            {
                "table_id": table.id.removesuffix(".px"),
                "edition": edition.lang,
                "title": edition.title,
                "coords": coords,
                "labels": labels,
                "roles": roles,
                "value": row.get("value"),
                "period": period,
                "status": None,
                "api_url": edition.url,
                "web_url": web_url(edition, table.id),
                "retrieved_at": retrieved_at,
                "latest_period": _latest_period(edition, binding),
            }
        )
    periods = []
    for year, month in parsed.periods:
        periods.append(f"{year}M{int(month):02d}" if month else str(year))
    claim = {
        "id": "c1",
        "op": op,
        "value": str(value),
        "display": display,
        "unit": None,
        "measure": _declared_measure(question, op),
        "cells": cells,
    }
    if derived.get("name") == "share_percent":
        claim["inputs"] = list(derived.get("inputs") or [])
    if any(note in {"men - women", "women - men"} for note in (binding.notes or [])):
        claim["formula"] = next(note for note in binding.notes if note in {"men - women", "women - men"})
        claim["inputs"] = list(derived.get("inputs") or [])
    from grund.frame import current_frame

    frame = current_frame()
    payload = frame.rail_payload() if frame is not None else {}
    return {
        "language": parsed.language,
        "question": question,
        "user_input": question,
        "asked": {"periods": periods, "op": op, "named_values": {}, "terms": [], "frame": payload},
        "frame": payload,
        "claims": [claim],
        "computed": True,
        "share_recompute": os.environ.get("GRUND_SHARE_RECOMPUTE", "").strip() == "1",
    }


def _claim_block(question: str, produced: dict) -> str | None:
    """None when this answer's claim matches its cells."""
    from grund_rails.cell_claim import check_claim

    calculated = produced["calculated"]
    table = produced["table"].id.removesuffix(".px")
    labels: dict[str, str] = {}
    cells: list[dict] = []
    periods: list[str] = []
    for row in calculated["rows"]:
        row_labels: dict[str, str] = {}
        period = ""
        for label in row.get("labels") or []:
            variable = str(label.get("variable_text") or label.get("variable") or "")
            text = str(label.get("label") or "")
            code = str(label.get("code") or "")
            if _looks_like_time(variable, code):
                period = code or text
            elif variable:
                row_labels[variable] = text
                labels.setdefault(variable, text)
        cells.append(
            {"table": table, "value": row.get("value"), "period": period, "labels": row_labels}
        )
        if period:
            periods.append(period)
    derived_block = calculated.get("derived") or {}
    derived = derived_block.get("value")
    value = derived if derived not in (None, "") else calculated.get("primary_raw")
    period = " to ".join(periods) if len(set(periods)) > 1 else (periods[-1] if periods else "")
    claim = {"value": value, "table": table, "period": period, "labels": labels}
    if derived_block.get("name") == "share_percent":
        claim["inputs"] = list(derived_block.get("inputs") or [])
    produced["claim"] = claim
    produced["claim_cells"] = cells
    reason = check_claim(question, claim, cells)
    # The sentence was computed from these rows. undeclared_number is a
    # checker miss, on this path and on the tools path. A claim that was
    # not computed still refuses.
    from grund_rails.cell_claim import rail_effect

    if rail_effect(reason, [reason] if reason else None, computed=True) == "pass":
        return None
    return reason


def _with_earlier_period(binding: Binding) -> Binding | None:
    """The previous period on the same table, when the latest cell was empty.

    A present-tense question is pinned to the last label. That label can be
    a missing cell (``..``). Stepping back stays on the series that was
    retrieved instead of answering from a different table.
    """
    if binding.operation not in {"level", "per_capita"}:
        return None
    if not binding.time_var or len(binding.time_codes) != 1:
        return None
    variable = binding.edition.variable(binding.time_var)
    if variable is None:
        return None
    codes = variable.codes()
    current = binding.time_codes[0]
    if current not in codes:
        return None
    index = codes.index(current)
    if index == 0:
        return None
    previous = codes[index - 1]
    selections = []
    for entry in binding.selections:
        values = [str(value) for value in entry["selection"]["values"]]
        if entry["code"] == binding.time_var:
            values = [previous if value == current else value for value in values]
        selections.append({"code": entry["code"], "selection": {"filter": "item", "values": values}})
    return Binding(
        edition=binding.edition,
        selections=selections,
        operation=binding.operation,
        score=binding.score,
        time_var=binding.time_var,
        time_codes=[previous],
        group_var=binding.group_var,
        part_code=binding.part_code,
        whole_code=binding.whole_code,
        rebase_code=binding.rebase_code,
        target_code=binding.target_code,
        notes=list(binding.notes) + [f"period {current} had no figure; used {previous}"],
        official_measure=binding.official_measure,
    )


_PLACE_SKIP = {
    "population", "female", "females", "male", "males", "index", "change",
    "price", "consumer", "migration", "internal", "annual", "total", "people",
    "konur", "karlar", "visitala", "neysluverds", "manfjoldi", "percent",
    "percentage", "iceland", "island", "hlutfall", "together", "counting",
}
_DISAMBIGUATORS = (
    "municipality", "sveitarfelag", "region", "landshluti", "capital",
    "hofudborg", "postcode", "urban nuclei", "byggdakjarni", "whole country",
)


def month_clarify_enabled() -> bool:
    return os.environ.get("GRUND_CLARIFY_MONTH", "").lower() in {"1", "true", "yes"}


def underspecified_cpi_month(parsed: ParsedQuestion) -> bool:
    """A CPI question with a year and no month.

    Off unless GRUND_CLARIFY_MONTH is set. The scored default cites the annual
    average. An explicit annual-average question is not this case.
    """
    if not month_clarify_enabled():
        return False
    if not parsed.periods or any(month is not None for _year, month in parsed.periods):
        return False
    folded = parsed.folded
    if "annual average" in folded or "arsmedal" in folded:
        return False
    return (
        "consumer price" in folded
        or "neysluverd" in folded
        or re.search(r"\b(cpi|vnv)\b", folded) is not None
    )


def _with_source_line(prose: str, language: str, table_id: str, edition: Edition, binding: Binding, calculated: dict) -> str:
    """The sentence the user reads names the table and the link."""
    from grund.answer import source_line

    filters = []
    for row in (calculated.get("rows") or [])[:2]:
        for label in row.get("labels") or []:
            text = str(label.get("label") or "")
            variable = str(label.get("variable") or label.get("variable_text") or "")
            if _looks_like_time(variable, str(label.get("code") or "")):
                continue
            if text and text not in filters:
                filters.append(text)
    period = ""
    if binding.time_codes:
        period = "–".join(str(code) for code in binding.time_codes[:2])
    derived = calculated.get("derived") or {}
    calculated_by_grund = binding.operation in {"difference", "yoy_pct", "share", "sum"} or derived.get("name") in {
        "yoy_pct",
        "share_percent",
        "difference",
        "rebase",
    }
    line = source_line(
        language,
        table_id,
        filters,
        period,
        web_url(edition, table_id),
        str(getattr(edition, "updated", "") or ""),
        calculated_by_grund,
    )
    stem = (table_id or "").removesuffix(".px")
    from grund.bind2 import attach_derivation

    derived_from = attach_derivation(binding, edition, calculated.get("rows") or [], calculated.get("derived"))
    if derived_from is not None and derived_from.sentence(language) not in prose:
        prose = prose.rstrip() + " " + derived_from.sentence(language)
    if "px.hagstofa.is" in prose and stem and stem in prose:
        return prose
    if line in prose:
        return prose
    return prose.rstrip() + " " + line


def web_url(edition: Edition, table_id: str) -> str:
    """Citation URL.

    The PxWeb HTML tree answers 200 for a database and 404 for a table path,
    so the link that actually identifies the table is the API URL.
    """
    return edition.url


class Engine:
    def __init__(
        self,
        catalogue: Catalogue,
        client: PxWebClient | None = None,
        rails: RailEngine | None = None,
        chat: ChatClient | None = None,
        planner: str | None = None,
    ) -> None:
        self.catalogue = catalogue
        self.client = client or PxWebClient(rate=4.0)
        self.rails = rails or default_engine()
        self.chat = chat or ChatClient()
        self.planner = planner or os.environ.get("GRUND_PLANNER", "auto")
        from grund_rails.vangrail_client import require_checker

        require_checker()
        self._listing: ListingRetriever | None = None
        self._listing_ready = False
        self._lang_index = None
        self._lang_ready = False
        # The default answer runs hybrid as well as the ranker. Hybrid cannot
        # start without the value-label index, so a wide catalogue refuses to
        # boot instead of answering from the ranker alone.
        from grund.toolpath import answer_path

        tables = getattr(catalogue, "tables", None)
        if answer_path() == "ranker" and isinstance(tables, list) and len(tables) >= 100:
            self._require_value_index()

    def ask(self, question: str, language: str | None = None) -> dict[str, Any]:
        if getattr(self, "_ask_depth", 0):
            return self._ask_topic(question, language)
        self._ask_depth = 1
        from grund.frame import annotate_latest, frame_enabled, frame_question, push_frame, reset_frame

        token = push_frame(None)
        framed = None
        try:
            original = question
            if frame_enabled():
                framed = frame_question(original)
                if framed.blocked:
                    from grund.parse import parse_question as _parse

                    parsed = _parse(original, language)
                    kind = "out_of_scope" if framed.blocked in {"opinion", "non_statistics"} else "no_table"
                    return self._finish_refusal(
                        parsed,
                        kind,
                        [],
                        time.perf_counter(),
                        [],
                        detail=framed.blocked,
                    )
                if framed.use:
                    push_frame(framed)
                    if framed.pipeline_text:
                        question = framed.pipeline_text
                    if language is None:
                        language = framed.language
            result = self._ask_topic(question, language)
            return annotate_latest(result, framed if framed is not None and framed.use else None)
        finally:
            self._ask_depth = 0
            reset_frame(token)

    def _ask_topic(self, question: str, language: str | None = None) -> dict[str, Any]:
        """State the baseline when its two paths already agreed.

        The topic prior reorders only the questions those paths did not share.
        A two-part question is decided on each half, which is what `ask` sees
        once the sentence is split.
        """
        from grund.compound import split_question as _split
        from grund.topic_prior import baseline_paths_agreed, enabled as prior_enabled

        owner = False
        if prior_enabled() and not getattr(self, "_prior_guarded", False) and _split(question) is None:
            owner = True
            self._prior_guarded = True
            saved = os.environ.get("GRUND_TOPIC_PRIOR")
            os.environ["GRUND_TOPIC_PRIOR"] = "0"
            try:
                baseline = self._ask_with_prior(question, language)
            finally:
                if saved is None:
                    os.environ.pop("GRUND_TOPIC_PRIOR", None)
                else:
                    os.environ["GRUND_TOPIC_PRIOR"] = saved
            if baseline_paths_agreed(baseline):
                self._prior_guarded = False
                return baseline
        try:
            return self._ask_with_prior(question, language)
        finally:
            if owner:
                self._prior_guarded = False

    def _ask_with_prior(self, question: str, language: str | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        original = question
        from grund.judgesim_fix import enabled, expand_question
        from grund.parse import resolve_references

        if enabled():
            question = expand_question(question)
        question = resolve_references(question)
        parsed = parse_question(question, language)
        rail_log = []
        blocked = self._blocked("input", original, {"question": original}, rail_log)
        if blocked is not None:
            return self._finish_refusal(parsed, "injection", rail_log, started, candidates=[])

        from grund.toolpath import dispatch

        routed = dispatch(self, question, parsed, rail_log, started)
        if routed is not None:
            return routed

        from grund.toolpath import answer_path

        if (
            answer_path() == "ranker"
            and not getattr(self, "_gate_active", False)
            and getattr(self, "_pinned_hit", None) is None
            and split_question(question) is None
        ):
            self._gate_active = True
            try:
                ranker = self.ask(question, language)
            finally:
                self._gate_active = False
            detail = ranker.get("detail")
            if isinstance(detail, dict) and detail.get("kind") in {"non_statistics", "opinion", "future"}:
                return ranker
            return self._agree_with_hybrid(question, parsed, ranker, rail_log, started)

        pieces = split_question(question)
        if pieces is not None and getattr(self, "_pinned_hit", None) is None:
            return self._answer_pieces(question, pieces, parsed, rail_log, started)

        signal = clearly_out_of_scope(question)
        if signal is None:
            from grund.scope import uncovered_subject_nouns

            missing_nouns = uncovered_subject_nouns(question, self.catalogue)
            if missing_nouns:
                signal = {"kind": "non_statistics", "uncovered": missing_nouns}
        if signal is not None:
            # A future year is not "absent from the catalogue". The other two
            # signals are subjects the office does not publish.
            kind = "no_table" if signal["kind"] == "future" else "out_of_scope"
            return self._finish_refusal(
                parsed,
                kind,
                rail_log,
                started,
                candidates=[],
                detail=signal,
            )
        if underspecified_cpi_month(parsed):
            return self._finish_refusal(
                parsed,
                "clarify_month",
                rail_log,
                started,
                candidates=[],
                detail={"reason": "month_missing"},
            )

        years = [year for year, _month in parsed.periods]
        value_bindings: dict = {}
        pinned = getattr(self, "_pinned_hit", None)
        if pinned is not None:
            hits = [pinned]
            search_hits = hits
            value_bindings = {pinned.table.id: []}
        else:
            # Catalogue search is the default. The value-label index is opt-in
            # (GRUND_PATH=index, tools, or hybrid). Loading it on every ask
            # sent the right table to bind_values and the wrong row.
            listed = None
            from grund.toolpath import answer_path

            if answer_path() == "index":
                self._require_value_index()
                listed, value_bindings = self._lang_shortlist(question)
            if listed:
                # The language index already prefers the headline series.
                # A second filter here was sending overnight stays and the
                # dollar rate off the table that index ranked first.
                hits = listed
                search_hits = listed
            else:
                from grund.headline import prefer_headline
                from grund.rerank import maybe_rerank, search_k

                found = self.catalogue.search(question, k=search_k(), years=years)
                found = maybe_rerank(self.catalogue, question, found, years)
                search_hits = prefer_headline(found, question)
                from grund.iscover import apply_is_cover

                search_hits = apply_is_cover(self.catalogue, search_hits, question, parsed.language)
                from grund.istown import apply_is_town

                search_hits = apply_is_town(self.catalogue, search_hits, question, parsed.language)
                from grund.isshare import apply_is_share

                search_hits = apply_is_share(self.catalogue, search_hits, question, parsed.language)
                from grund.isjobsex import apply_is_jobsex

                search_hits = apply_is_jobsex(self.catalogue, search_hits, question, parsed.language)
                from grund.isjobs import apply_is_jobs

                search_hits = apply_is_jobs(self.catalogue, search_hits, question, parsed.language)
                from grund.isbirths import apply_is_births

                search_hits = apply_is_births(self.catalogue, search_hits, question, parsed.language)
                from grund.isregion import apply_is_region

                search_hits = apply_is_region(self.catalogue, search_hits, question, parsed.language)
                from grund.isgdp import apply_is_gdp

                search_hits = apply_is_gdp(self.catalogue, search_hits, question, parsed.language)
                from grund.istrade import apply_is_trade

                search_hits = apply_is_trade(self.catalogue, search_hits, question, parsed.language)
                from grund.iscpi import apply_is_cpi

                search_hits = apply_is_cpi(self.catalogue, search_hits, question, parsed.language)
                from grund.iswage import apply_is_wage

                search_hits = apply_is_wage(self.catalogue, search_hits, question, parsed.language)
                from grund.isstays import apply_is_stays

                search_hits = apply_is_stays(self.catalogue, search_hits, question, parsed.language)
                from grund.isquarter import apply_is_quarter

                search_hits = apply_is_quarter(self.catalogue, search_hits, question, parsed.language)
                from grund.ispop import apply_is_pop

                search_hits = apply_is_pop(self.catalogue, search_hits, question, parsed.language)
                from grund.isorigin import apply_is_origin

                search_hits = apply_is_origin(self.catalogue, search_hits, question, parsed.language)
                from grund.isbuilding import apply_is_building

                search_hits = apply_is_building(self.catalogue, search_hits, question, parsed.language)
                from grund.measure_guard import apply_measure_guard

                search_hits = apply_measure_guard(self.catalogue, search_hits, question, parsed.language)
                from grund.frame import current_frame, order_hits

                search_hits = order_hits(self.catalogue, search_hits, current_frame())
                from grund.topic_prior import maybe_topic_prior

                search_hits = maybe_topic_prior(self.catalogue, question, search_hits)
                from grund.topicmap import rerank

                search_hits = rerank(self.catalogue, question, search_hits, parsed.language)
                hits = search_hits
        if pinned is None and self.planner == "model" and not value_bindings:
            listed = self._listing_hits(question, parsed.language, years)
            if listed:
                hits = listed
        from grund.sexdiff import binding_for, is_sex_difference

        # GRUND_SEXDIFF is off. On, a sex-count gap is the only attempt.
        # A named municipality uses that municipality's cells. Operand order
        # follows the question: more X than Y, and X minus Y, are X minus Y.
        sex_only = False
        if is_sex_difference(question):
            forced = binding_for(self.catalogue, parsed, question, hits)
            if forced is None:
                return self._finish_refusal(
                    parsed,
                    "no_table",
                    rail_log,
                    started,
                    [],
                    detail={"reason": "sex difference"},
                    planner="sexdiff",
                )
            binding, table = forced
            planner_name = "sexdiff"
            planner_notes = list(binding.notes)
            sex_only = True
        else:
            binding, table, hit_rows, planner_name, planner_notes = self._choose(
                parsed, hits, search_hits, value_bindings
            )
        candidates = []
        for hit in hits[:4]:
            edition = hit.table.edition(parsed.language) or hit.table.edition("en")
            candidates.append(
                {
                    "table_id": hit.table.id,
                    "title": edition.title if edition else hit.table.id,
                    "score": round(hit.score, 4),
                    "url": edition.url if edition else "",
                    "web_url": edition.url if edition else "",
                }
            )
        if binding is None or table is None:
            # Retrieval already ran. A miss here is a refusal with the candidate
            # links, including when the top table shares little wording with the
            # question. Out of scope is only the clear-signal check above.
            kind = "clarify" if planner_notes == ["ambiguous"] else "no_table"
            return self._finish_refusal(parsed, kind, rail_log, started, candidates, planner=planner_name)

        attempts = [(binding, table, planner_name, planner_notes)]
        if not sex_only and planner_name in {"deterministic", "hybrid", "model"}:
            # A model query that does not fetch falls back to the code plan,
            # ranked on the original search rather than the model shortlist.
            pool = search_hits if self.planner == "model" else hits
            for _score, other_binding, other_table in self._rank(parsed, pool):
                if any(
                    previous_table.id == other_table.id and previous.selections == other_binding.selections
                    for previous, previous_table, _name, _notes in attempts
                ):
                    continue
                notes = list(other_binding.notes)
                if planner_name == "hybrid":
                    notes.append("hybrid query did not produce a figure")
                attempts.append((other_binding, other_table, "deterministic", notes))

        produced = None
        last_detail = None
        index = 0
        walked = 0
        blocked_sources: list[dict] = []
        while index < len(attempts):
            binding, table, planner_name, planner_notes = attempts[index]
            produced = self._produce(parsed, binding, table, question, rail_log)
            if index >= 20:
                produced = None
                break
            if produced.get("ok"):
                verdict = _guard_verdict(question, parsed, produced)
                rail_log.append(verdict)
                produced["verdict"] = verdict
                categories = set(verdict.get("categories") or [])
                passed = verdict.get("status") == "passed" and verdict.get("certain") is not False
                from grund_rails.cell_claim import rail_effect

                effect = "pass" if passed else rail_effect(
                    verdict.get("reason"), verdict.get("categories"), computed=True
                )
                if effect == "pass":
                    from grund_rails.cell_claim import question_match_claims

                    if not question_match_claims(question, produced.get("claims") or []):
                        effect = "retry"
                        verdict = {
                            **verdict,
                            "status": "blocked",
                            "reason": "cited cell does not match the question",
                            "categories": ["unsupported_cell"],
                        }
                        produced["verdict"] = verdict
                if effect != "pass":
                    from grund.istown import town_cell_clears

                    if town_cell_clears(question, parsed.language, produced, verdict):
                        effect = "pass"
                        verdict = {**verdict, "status": "passed", "certain": True, "town_cell": True}
                        produced["verdict"] = verdict
                if effect != "pass":
                    from grund.isshare import share_cell_clears

                    if share_cell_clears(question, parsed.language, produced, verdict):
                        effect = "pass"
                        verdict = {**verdict, "status": "passed", "certain": True, "share_cell": True}
                        produced["verdict"] = verdict
                if effect != "pass":
                    from grund.isbirths import birth_cell_clears

                    if birth_cell_clears(question, parsed.language, produced, verdict):
                        effect = "pass"
                        verdict = {**verdict, "status": "passed", "certain": True, "birth_cell": True}
                        produced["verdict"] = verdict
                if effect != "pass":
                    from grund.isregion import region_cell_clears

                    if region_cell_clears(question, parsed.language, produced, verdict):
                        effect = "pass"
                        verdict = {**verdict, "status": "passed", "certain": True, "region_cell": True}
                        produced["verdict"] = verdict
                if effect != "pass":
                    from grund.isgdp import gdp_cell_clears

                    if gdp_cell_clears(question, parsed.language, produced, verdict):
                        effect = "pass"
                        verdict = {**verdict, "status": "passed", "certain": True, "gdp_cell": True}
                        produced["verdict"] = verdict
                if effect != "pass":
                    from grund.istrade import trade_cell_clears

                    if trade_cell_clears(question, parsed.language, produced, verdict):
                        effect = "pass"
                        verdict = {**verdict, "status": "passed", "certain": True, "trade_cell": True}
                        produced["verdict"] = verdict
                if effect != "pass":
                    from grund.iscpi import cpi_cell_clears

                    if cpi_cell_clears(question, parsed.language, produced, verdict):
                        effect = "pass"
                        verdict = {**verdict, "status": "passed", "certain": True, "cpi_cell": True}
                        produced["verdict"] = verdict
                if effect != "pass":
                    from grund.iswage import wage_cell_clears

                    if wage_cell_clears(question, parsed.language, produced, verdict):
                        effect = "pass"
                        verdict = {**verdict, "status": "passed", "certain": True, "wage_cell": True}
                        produced["verdict"] = verdict
                if effect != "pass":
                    from grund.isstays import stays_cell_clears

                    if stays_cell_clears(question, parsed.language, produced, verdict):
                        effect = "pass"
                        verdict = {**verdict, "status": "passed", "certain": True, "stays_cell": True}
                        produced["verdict"] = verdict
                if effect != "pass":
                    from grund.isquarter import quarter_cell_clears

                    if quarter_cell_clears(question, parsed.language, produced, verdict):
                        effect = "pass"
                        verdict = {**verdict, "status": "passed", "certain": True, "quarter_cell": True}
                        produced["verdict"] = verdict
                if effect != "pass":
                    from grund.ispop import pop_cell_clears

                    if pop_cell_clears(question, parsed.language, produced, verdict):
                        effect = "pass"
                        verdict = {**verdict, "status": "passed", "certain": True, "pop_cell": True}
                        produced["verdict"] = verdict
                if effect == "pass":
                    from grund.istown import town_states_country

                    if town_states_country(question, parsed.language, produced):
                        effect = "retry"
                        verdict = {
                            **verdict,
                            "status": "blocked",
                            "reason": "named municipality is not the country total",
                            "categories": ["unsupported_cell"],
                        }
                        produced["verdict"] = verdict
                if effect == "pass":
                    produced["planner_name"] = planner_name
                    produced["planner_notes"] = planner_notes
                    break
                edition = produced["edition"]
                blocked_sources.append(
                    {
                        "table_id": produced["table"].id,
                        "title": edition.title,
                        "url": edition.url,
                        "reason": verdict.get("reason"),
                    }
                )
                last_detail = verdict.get("reason")
                produced = None
                if effect == "retry":
                    index += 1
                    continue
                break
            last_detail = produced.get("detail")
            # A 429 or a dropped connection is not evidence that the next table
            # is the one the question asked for. A bad query still falls through.
            if produced.get("transport"):
                produced = None
                break
            if (
                walked < 6
                and not parsed.periods
                and "no numeric" in str(last_detail or "")
                and __import__("grund.heuristics", fromlist=["enabled"]).enabled("empty_latest_period")
            ):
                earlier = _with_earlier_period(binding)
                if earlier is not None:
                    walked += 1
                    attempts[index] = (earlier, table, planner_name, list(earlier.notes))
                    produced = None
                    continue
            produced = None
            index += 1
        if produced is None:
            return self._finish_refusal(
                parsed,
                "no_table",
                rail_log,
                started,
                candidates,
                detail=last_detail,
                planner=planner_name,
                sources=blocked_sources,
            )
        prose = produced["prose"]
        calculated = produced["calculated"]
        source_bits = produced
        allowed = self._allowed_figures(
            calculated["rows"], calculated["derived"], produced["population_row"]
        )
        # The model picks a table and codes. The sentence is the template,
        # whose figures come only from the cells just fetched.
        if produced.get("planner_name") == "model":
            prose_rail = None
        else:
            prose, prose_rail = self._maybe_rephrase(
                prose,
                calculated,
                allowed,
                parsed,
                source_bits["edition"],
                source_bits["note_text"] if not source_bits["context_blocked"] else "",
            )
        if prose_rail:
            rail_log.append(prose_rail)

        source = self._source(
            source_bits["table"],
            source_bits["edition"],
            source_bits["binding"],
            calculated,
            source_bits["notes"],
            source_bits["flags"],
            source_bits["payload"],
            source_bits["planner_name"],
            source_bits["planner_notes"],
            source_bits["plan_audit"],
            withheld=source_bits["context_blocked"],
        )
        value_display = format_stat(calculated["primary_raw"], parsed.language)
        prose = _with_source_line(
            prose,
            parsed.language,
            source_bits["table"].id,
            source_bits["edition"],
            source_bits["binding"],
            calculated,
        )
        from grund.bind2 import cell_was_replaced, remember_query

        remember_query(question, source_bits["table"].id, source_bits["binding"])
        built = {
            "answer": prose,
            "refused": False,
            "clarify": False,
            "language": parsed.language,
            "value": calculated["primary_raw"],
            "value_display": value_display,
            "table_id": source_bits["table"].id,
            "tables": [source_bits["table"].id],
            "operation": source_bits["binding"].operation,
            "planner": produced.get("planner_name"),
            "source": source,
            "claims": produced.get("claims") or [],
            "verdict": produced.get("verdict"),
            "retries": sum(1 for item in rail_log if item.get("status") == "blocked"),
            "rails": rail_log,
            "candidates": candidates,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "features": __import__("grund.calibrate", fromlist=["feature_row"]).feature_row(
                question,
                {
                    "table_id": source_bits["table"].id,
                    "value": calculated["primary_raw"],
                    "claims": produced.get("claims") or [],
                    "candidates": candidates,
                },
            ),
        }
        built["bind2_replaced"] = cell_was_replaced(source_bits["binding"].notes)
        if getattr(self, "_gate_active", False) or getattr(self, "_defer_present", False):
            return built
        return self._maybe_abstain(parsed, built)

    def _answer_pieces(self, question: str, pieces, parsed: ParsedQuestion, rail_log: list, started: float) -> dict:
        kind, left_question, right_question, scale = pieces
        pair = self._pair_hits(question)
        if pair is not None:
            left = self._ask_pinned(left_question, parsed.language, pair[0])
            right = self._ask_pinned(right_question, parsed.language, pair[1])
        else:
            self._defer_present = True
            try:
                left = self.ask(left_question, parsed.language)
                right = self.ask(right_question, parsed.language)
            finally:
                self._defer_present = False
        merged = combine_answers(kind, left, right, scale, parsed.language)
        if merged is None:
            return self._finish_refusal(
                parsed,
                "no_table",
                rail_log,
                started,
                candidates=[],
                detail="one of the two parts had no figure",
            )
        merged["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        merged["rails"] = rail_log + list(left.get("rails") or []) + list(right.get("rails") or [])
        left_features = left.get("features") or {}
        right_features = right.get("features") or {}
        if left_features or right_features:
            merged["features"] = {
                name: (float(left_features.get(name) or 0.0) + float(right_features.get(name) or 0.0)) / 2.0
                for name in ("margin", "rerank", "measure", "period", "agreement")
            }
        return self._maybe_abstain(parsed, merged)

    def _choose(
        self,
        parsed: ParsedQuestion,
        hits: list[Hit],
        search_hits: list[Hit] | None = None,
        value_bindings: dict | None = None,
    ) -> tuple[Binding | None, Table | None, list, str, list[str]]:
        base = search_hits if search_hits is not None else hits
        deterministic = self._deterministic(parsed, base, value_bindings or {})
        if self.planner == "model":
            return self._choose_model(parsed, hits, deterministic, value_bindings or {})
        if self.planner == "hybrid":
            return self._choose_hybrid(parsed, hits, deterministic)
        use_llm = self.planner == "llm" or (self.planner == "auto" and self.chat.settings.enabled())
        if not use_llm:
            return (*deterministic[:2], hits, "deterministic", deterministic[2])
        try:
            planned = self._llm_plan(parsed, hits)
        except Exception as exc:  # noqa: BLE001
            binding, table, notes = deterministic
            return binding, table, hits, "deterministic", notes + [f"llm planner failed: {exc}"]
        if planned is None:
            return None, None, hits, "llm", ["refused"]
        if planned == "fallback":
            binding, table, notes = deterministic
            return binding, table, hits, "deterministic", notes + ["llm plan did not validate"]
        binding, table = planned
        return binding, table, hits, "llm", ["validated structured query"]

    def _listing_hits(self, question: str, language: str, years: list[int]) -> list[Hit] | None:
        """Model shortlist. The deterministic search result is left as it was."""
        if not self._listing_ready:
            self._listing_ready = True
            path = listing_path()
            if path is not None:
                self._listing = ListingRetriever(self.catalogue, path)
        if self._listing is None:
            return None
        return self._listing.search(question, language, k=12, years=years)

    def _choose_model(self, parsed: ParsedQuestion, hits: list[Hit], deterministic, value_bindings: dict | None = None):
        """Model picks a table from the shortlist. Codes come from bind_values when they cover it."""
        binding, table, notes = deterministic
        if not self.chat.settings.enabled():
            return binding, table, hits, "deterministic", list(notes) + ["model: no server"]
        value_bindings = value_bindings or {}
        cards = _cards_from_bindings(hits, parsed, value_bindings) or shortlist(hits, parsed, limit=5)
        if not cards:
            return binding, table, hits, "deterministic", list(notes) + ["model: empty shortlist"]
        editions = {}
        for table_id, edition, _variables in cards:
            for hit in hits:
                if hit.table.id == table_id:
                    editions[table_id] = (hit.table, edition)
                    break
        schema = {
            "type": "json_schema",
            "json_schema": {"name": "px_query", "strict": True, "schema": query_schema(cards, parsed)},
        }
        last_error = ""
        for _attempt in range(3):
            try:
                raw = self.chat.complete(
                    model_messages(parsed, hits, last_error, cards=cards if value_bindings else None),
                    response_format=schema,
                    max_tokens=500,
                )
                plan = parse_json_object(raw)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                continue
            table_id = plan.get("table_id")
            if table_id not in editions:
                last_error = f"unknown table {table_id}"
                continue
            chosen_table, edition = editions[table_id]
            if value_bindings.get(table_id):
                built = binding_from_values(edition, parsed, value_bindings[table_id])
            else:
                built = binding_from_model(edition, parsed, plan.get("selections") or {})
            if built is None:
                last_error = "query would not bind"
                continue
            try:
                validate(edition, built.selections)
            except ValidationError as exc:
                last_error = str(exc)
                continue
            return built, chosen_table, hits, "model", ["model query kept"] + list(built.notes)
        return binding, table, hits, "deterministic", list(notes) + [f"model fell back: {last_error}"]

    def _choose_hybrid(self, parsed: ParsedQuestion, hits: list[Hit], deterministic):
        binding, table, notes = deterministic
        det_id = table.id if table is not None else None
        if not self.chat.settings.enabled():
            return binding, table, hits, "deterministic", notes + ["hybrid: no model server"]
        cards = shortlist(hits, parsed)
        if not cards:
            return binding, table, hits, "deterministic", notes + ["hybrid: empty shortlist"]
        rank = {table_id: index for index, (table_id, _edition, _variables) in enumerate(cards, start=1)}
        editions = {table_id: (self._table_for(hits, table_id), edition) for table_id, edition, _variables in cards}
        try:
            raw = self.chat.complete(
                messages_for(parsed, cards),
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "px_query", "strict": True, "schema": query_schema(cards, parsed)},
                },
                max_tokens=500,
            )
            plan = parse_json_object(raw)
        except Exception as exc:  # noqa: BLE001
            return binding, table, hits, "deterministic", notes + [f"hybrid planner failed: {exc}"]
        table_id = plan.get("table_id")
        band = confidence_band(plan.get("confidence"))
        if table_id not in editions or plan.get("action") != "query" or not use_model_selections(
            band, table_id, det_id, rank.get(table_id, 99)
        ):
            return binding, table, hits, "deterministic", notes + [
                f"hybrid fell back: {plan.get('action')} confidence {band}"
            ]
        chosen_table, edition = editions[table_id]
        built = binding_from_model(edition, parsed, plan.get("selections") or {})
        if built is None:
            return binding, table, hits, "deterministic", notes + ["hybrid fell back: query would not bind"]
        try:
            validate(edition, built.selections)
        except ValidationError as exc:
            return binding, table, hits, "deterministic", notes + [f"hybrid fell back: {exc}"]
        # Same table, different codes: the value is the uncertain case, so the
        # deterministic plan is the one that is kept. A different table in the
        # shortlist can still stand.
        if binding is not None and table_id == det_id and selection_signature(built) != selection_signature(binding):
            return binding, table, hits, "deterministic", notes + [
                "hybrid fell back: model codes disagree with the deterministic plan"
            ]
        return built, chosen_table, hits, "hybrid", [f"hybrid kept the model query ({band})"] + list(built.notes)

    def _table_for(self, hits: list[Hit], table_id: str) -> Table:
        for hit in hits:
            if hit.table.id == table_id:
                return hit.table
        raise KeyError(table_id)

    def _rank(self, parsed: ParsedQuestion, hits: list[Hit]) -> list[tuple[float, Binding, Table]]:
        ranked: list[tuple[float, Binding, Table]] = []
        for hit in hits:
            edition = hit.table.edition(parsed.language) or hit.table.edition("en")
            if edition is None:
                continue
            binding = bind(edition, parsed)
            if binding is None:
                continue
            try:
                validate(edition, binding.selections)
            except ValidationError:
                continue
            ranked.append((hit.score * 10 + min(binding.score, 2.5) * 0.2, binding, hit.table))
        ranked.sort(key=lambda item: (-round(item[0], 6), item[2].id))
        return ranked

    def _allowed_figures(self, rows, derived, population) -> list[float]:
        """Fetched cells, plus label digits and the cell's magnitude."""
        return allowed_numbers(rows, derived, population)

    def _ask_pinned(self, question: str, language: str, hit: Hit) -> dict:
        previous = getattr(self, "_pinned_hit", None)
        self._pinned_hit = hit
        try:
            return self.ask(question, language)
        finally:
            self._pinned_hit = previous

    def _pair_hits(self, question: str) -> list[Hit] | None:
        """One table for each half, from retrieve_pair, on the index path.

        The default path searches each half in the catalogue. The value-label
        index's pair call was sending the harmonised price index to the
        domestic CPI.
        """
        from grund.toolpath import answer_path

        if answer_path() != "index":
            return None
        index = self._language_index(required=False)
        if index is None:
            return None
        from grund_lang import retrieve_pair

        found: list[Hit] = []
        for candidate in retrieve_pair(index, question, k=5):
            table = self.catalogue.by_id.get(candidate.table_id + ".px") or self.catalogue.by_id.get(candidate.table_id)
            if table is None:
                return None
            found.append(
                Hit(
                    table=table,
                    score=float(candidate.score),
                    bm25=float(candidate.bm25),
                    cosine=float(candidate.cosine),
                    value_boost=float(candidate.value_bm25),
                )
            )
        return found if len(found) >= 2 else None

    def _lang_shortlist(self, question: str, k: int = 20) -> tuple[list[Hit] | None, dict]:
        """Top-20 metadata shortlist. A blocked claim tries the next table.

        When the parse-then-tools path lands, it becomes the primary caller
        and this ranker stays the fallback. The rail contract does not change.
        """
        index = self._language_index()
        if index is None:
            return None, {}
        from grund_lang import retrieve

        hits: list[Hit] = []
        bindings: dict = {}
        for candidate in retrieve(index, question, k=k):
            table = self.catalogue.by_id.get(candidate.table_id + ".px") or self.catalogue.by_id.get(candidate.table_id)
            if table is None:
                continue
            hits.append(
                Hit(
                    table=table,
                    score=float(candidate.score),
                    bm25=float(candidate.bm25),
                    cosine=float(candidate.cosine),
                    value_boost=float(candidate.value_bm25),
                )
            )
            bindings[table.id] = list(candidate.bindings)
        return (hits or None), bindings

    def _require_value_index(self) -> None:
        """tools, hybrid, and index refuse to start without the value-label index."""
        self._language_index(required=True)

    def _lang_index_dir(self):
        from pathlib import Path

        raw = os.environ.get("GRUND_LANG_INDEX", "").strip()
        if raw:
            return Path(raw)
        root = Path(__file__).resolve().parents[2] / "data" / "index-lang"
        if (root / "manifest.json").is_file() and (root / "embeddings.npy").is_file():
            return root
        return Path("data/index-lang")

    def _language_index(self, *, required: bool = False):
        tables = getattr(self.catalogue, "tables", None)
        wide = isinstance(tables, list) and len(tables) >= 100
        if not wide and not required:
            return None
        if self._lang_ready:
            if self._lang_index is None and required:
                raise _index_offline(self._lang_index_dir(), "the index did not load.")
            return self._lang_index
        import sys
        from pathlib import Path as _Path

        lang_dir = _Path(__file__).resolve().parents[2] / "lang"
        if lang_dir.is_dir() and str(lang_dir) not in sys.path:
            sys.path.insert(0, str(lang_dir))
        folder = self._lang_index_dir()
        if not (folder / "manifest.json").is_file() or not (folder / "embeddings.npy").is_file():
            self._lang_index = None
            self._lang_ready = True
            if required:
                raise _index_offline(
                    folder,
                    "manifest.json and embeddings.npy have to be in that directory. "
                    "The value-label postings are built with them.",
                )
            return None
        try:
            from grund_lang import load_index

            loaded = load_index(folder)
        except Exception as exc:
            raise _index_offline(folder, str(exc)) from exc
        if loaded is None:
            raise _index_offline(folder, "load_index returned nothing.")
        # Build the chargram value index from this catalogue. A saved
        # matrix (e5-large on one machine, an older chargram file on
        # another) made the hybrid path pick a different table.
        from grund_lang.index import build_index

        loaded = build_index(list(self.catalogue.tables), embed="chargram")
        self._lang_index = loaded
        self._lang_ready = True
        return self._lang_index

    def _deterministic(
        self, parsed: ParsedQuestion, hits: list[Hit], value_bindings: dict | None = None
    ) -> tuple[Binding | None, Table | None, list[str]]:
        if value_bindings:
            bound = self._bind_listed(parsed, hits, value_bindings)
            if bound is not None:
                return bound
        ranked = self._prefer_quoted_title(parsed, self._prefer_closed_series(parsed, self._rank(parsed, hits)))
        if not ranked:
            return None, None, []
        if self._ambiguous(parsed, ranked):
            return None, None, ["ambiguous"]
        _score, binding, table = ranked[0]
        if hits and hits[0].table.id != table.id:
            from grund.subject_veto import enabled as subject_enabled
            from grund.subject_veto import subject_gap

            leader = hits[0].table.edition(parsed.language) or hits[0].table.edition("en")
            chosen = table.edition(parsed.language) or table.edition("en")
            if subject_enabled() and leader and chosen and subject_gap(parsed.text, leader.title, chosen.title):
                return None, None, ["subject"]
        return binding, table, list(binding.notes)

    def _bind_listed(
        self, parsed: ParsedQuestion, hits: list[Hit], value_bindings: dict
    ) -> tuple[Binding | None, Table | None, list[str]] | None:
        """First shortlisted table whose bind_values codes validate."""
        from grund.langbind import combined_binding

        for hit in hits:
            edition = hit.table.edition(parsed.language) or hit.table.edition("en")
            if edition is None:
                continue
            built = combined_binding(edition, parsed)
            if built is None:
                continue
            return built, hit.table, list(built.notes)
        return None, None, ["no validated query"]

    def _prefer_closed_series(self, parsed: ParsedQuestion, ranked: list[tuple[float, Binding, Table]]):
        """Two vintages of one series, both covering the year, and almost the same score.

        The question quotes the shared title and not the end year. Prefer the
        vintage that stops sooner. A question that names an end year keeps that vintage.
        """
        if len(ranked) < 2 or not parsed.periods:
            return ranked
        first, second = ranked[0], ranked[1]
        if second[0] < first[0] * 0.98:
            return ranked
        asked = [year for year, _month in parsed.periods]
        left, right = first[1].edition.years(), second[1].edition.years()
        if not left or not right or not all(year in left and year in right for year in asked):
            return ranked
        stem = _series_stem(first[1].edition.title)
        if len(stem) < 12 or stem != _series_stem(second[1].edition.title):
            return ranked
        end_left, end_right = max(left), max(right)
        mentioned = {int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", parsed.folded)}
        if end_left in mentioned and end_right not in mentioned:
            return ranked
        if end_right in mentioned and end_left not in mentioned:
            return [second, first, *ranked[2:]]
        if end_right < end_left:
            return [second, first, *ranked[2:]]
        return ranked

    def _prefer_quoted_title(self, parsed: ParsedQuestion, ranked: list[tuple[float, Binding, Table]]):
        """The question pastes a table title. Keep that table when the neighbour is only close."""
        if len(ranked) < 2:
            return ranked
        first, second = ranked[0], ranked[1]
        if second[0] < first[0] * 0.90:
            return ranked
        if _quoted_len(parsed, second[1]) > _quoted_len(parsed, first[1]):
            return [second, first, *ranked[2:]]
        return ranked

    def _produce(self, parsed: ParsedQuestion, binding: Binding, table: Table, question: str, rail_log: list) -> dict:
        """Fetch and compute one binding. A failed share or a bad query returns ok=False."""
        edition = binding.edition
        try:
            validate(edition, binding.selections)
        except ValidationError as exc:
            return {"ok": False, "detail": str(exc)}
        population_row = None
        try:
            payload, plan_audit = self._fetch(table, edition, binding)
            if binding.operation == "per_capita":
                population_row = self._population(parsed, binding)
        except (PlanError, ArithmeticError, ValidationError) as exc:
            return {"ok": False, "detail": str(exc)}
        except PxWebError as exc:
            transport = exc.status in {None, 429} or (exc.status is not None and exc.status >= 500)
            return {"ok": False, "detail": str(exc), "transport": transport}
        except Exception as exc:  # noqa: BLE001 - a failed fetch is a refusal, not a made-up number
            return {"ok": False, "detail": str(exc), "transport": True}
        rows = extract_rows(payload, edition)
        from grund.bind2 import narrow_latest

        rows = narrow_latest(rows, binding)
        notes = footnotes(payload)
        note_text = "\n".join(note["text"] for note in notes)
        context_blocked = False
        if note_text.strip():
            context_results = self.rails.run("context", note_text, {"question": question})
            rail_log.extend(result.to_dict() for result in context_results)
            context_blocked = any(result.blocked_turn() for result in context_results)
        flags = release_flags(edition.title, note_text, edition.notes or "")
        try:
            calculated = compute(rows, binding, population=population_row)
        except ArithmeticError as exc:
            return {"ok": False, "detail": str(exc)}
        prose = render(
            parsed.language,
            edition,
            binding,
            calculated["rows"],
            calculated["primary_raw"],
            calculated["derived"],
            flags["preliminary"],
        )
        if any(note in {"men - women", "women - men"} for note in binding.notes):
            if parsed.language == "is":
                prose += " Munurinn er reiknaður úr þessum tveimur reitum."
            else:
                prose += " The difference was calculated from these two cells."
        return {
            "ok": True,
            "prose": prose,
            "calculated": calculated,
            "population_row": population_row,
            "edition": edition,
            "table": table,
            "binding": binding,
            "notes": notes,
            "note_text": note_text,
            "flags": flags,
            "payload": payload,
            "planner_name": None,
            "planner_notes": list(binding.notes),
            "plan_audit": plan_audit,
            "context_blocked": context_blocked,
        }

    def _ambiguous(self, parsed: ParsedQuestion, ranked: list[tuple[float, Binding, Table]]) -> bool:
        if len(ranked) < 2:
            return False
        # A named year is enough to pick the closer table. Clarifying is for a
        # question that names a place and no period.
        if parsed.periods:
            return False
        if any(marker in parsed.folded for marker in _DISAMBIGUATORS):
            return False
        first, second = ranked[0], ranked[1]
        if second[0] < first[0] * 0.93:
            return False
        if first[2].id == second[2].id:
            return False
        if _quoted_len(parsed, first[1]) != _quoted_len(parsed, second[1]):
            return False
        left = _specific_labels(first[1], parsed)
        right = _specific_labels(second[1], parsed)
        shared = left & right
        return bool(shared)

    def _llm_plan(self, parsed: ParsedQuestion, hits: list[Hit]):
        cards = []
        editions = {}
        for hit in hits[:5]:
            edition = hit.table.edition(parsed.language) or hit.table.edition("en")
            if edition is None:
                continue
            editions[hit.table.id] = (hit.table, edition)
            cards.append(_card(hit.table.id, edition, parsed))
        if not cards:
            return "fallback"
        messages = [
            {
                "role": "system",
                "content": (
                    "You choose a Statistics Iceland PxWeb query. "
                    "Reply with one JSON object and no other text. Do not calculate. "
                    'Refuse with {"action":"refuse"}. '
                    "Otherwise reply with "
                    '{"action":"query","table_id":"FILE.px","operation":"level",'
                    '"selections":[{"code":"VariableCode","values":["ValueCode"]}]}. '
                    "table_id must be one of the card ids. "
                    "selections must name every variable on that card. "
                    "values are the card's codes, never the labels. "
                    "operation is one of level, yoy_pct, share, difference, rebase, per_capita."
                ),
            },
            {
                "role": "user",
                "content": json_dumps({"question": parsed.text, "tables": cards}),
            },
        ]
        last_error = ""
        for _attempt in range(3):
            if last_error:
                messages.append({"role": "user", "content": f"The previous query was rejected: {last_error}"})
            raw = self.chat.complete(messages)
            try:
                plan = parse_json_object(raw)
            except (ValueError, json_error()) as exc:
                last_error = str(exc)
                messages.append({"role": "assistant", "content": raw[:2000]})
                continue
            if plan.get("action") == "refuse":
                return None
            table_id = plan.get("table_id")
            if table_id not in editions:
                last_error = f"unknown table {table_id}. Use one of: {', '.join(editions)}"
                messages.append({"role": "assistant", "content": raw[:2000]})
                continue
            table, edition = editions[table_id]
            selections = []
            for entry in plan.get("selections") or []:
                values = [str(value) for value in entry.get("values") or []]
                selections.append({"code": entry.get("code"), "selection": {"filter": "item", "values": values}})
            try:
                validate(edition, selections)
            except ValidationError as exc:
                last_error = str(exc)
                messages.append({"role": "assistant", "content": raw[:2000]})
                continue
            operation = plan.get("operation") or "level"
            if operation not in {"level", "yoy_pct", "share", "difference", "rebase", "per_capita"}:
                last_error = f"unknown operation {operation}"
                continue
            binding = bind(edition, parsed)
            if binding is None:
                binding = Binding(
                    edition=edition,
                    selections=selections,
                    operation=operation,
                    score=0,
                    time_var=None,
                    time_codes=[],
                )
            binding.selections = selections
            binding.operation = operation if not binding.official_measure else binding.operation
            return binding, table
        return "fallback"

    def _fetch(self, table: Table, edition: Edition, binding: Binding) -> tuple[dict, list[str]]:
        from grund.bind2 import enabled as bind2_enabled
        from grund.bind2 import guard_url

        if bind2_enabled():
            guard_url(edition.url)
        body = query_body(binding.selections)
        arguments = {"table_id": table.id, "url": edition.url, "query": body["query"]}
        plan = Plan()
        plan.read("pxweb.query", arguments)
        plan.lock()
        plan.check_call("pxweb.query", arguments)
        payload = self.client.post_json(edition.url, body)
        return payload, plan.audit

    def _population(self, parsed: ParsedQuestion, binding: Binding) -> dict:
        table = self.catalogue.by_id.get("MAN00101.px")
        if table is None:
            raise ArithmeticError("population table MAN00101.px is not in the index")
        edition = table.edition(parsed.language) or table.edition("en")
        if edition is None:
            raise ArithmeticError("population table has no edition")
        year = parsed.periods[0][0] if parsed.periods else None
        sex = _total_code(edition, "Kyn") or _total_code(edition, "Sex")
        age = _code_by_label(edition, "Aldur", "total") or _code_by_label(edition, "Age", "total")
        time_var = edition.time_variable()
        if time_var is None or year is None or sex is None or age is None:
            raise ArithmeticError("could not bind a population denominator")
        year_code = str(year) if str(year) in time_var.codes() else None
        if year_code is None:
            raise ArithmeticError(f"population table does not contain {year}")
        selections = [
            {"code": time_var.code, "selection": {"filter": "item", "values": [year_code]}},
            {"code": "Kyn" if edition.variable("Kyn") else "Sex", "selection": {"filter": "item", "values": [sex]}},
            {"code": "Aldur" if edition.variable("Aldur") else "Age", "selection": {"filter": "item", "values": [age]}},
        ]
        validate(edition, selections)
        payload, _audit = self._fetch(table, edition, Binding(
            edition=edition, selections=selections, operation="level", score=0, time_var=time_var.code, time_codes=[year_code]
        ))
        rows = [row for row in extract_rows(payload, edition) if row["value"] not in {None, ".", ".."}]
        if not rows:
            raise ArithmeticError("population query returned no cell")
        return rows[0]

    def _maybe_rephrase(self, prose, calculated, allowed, parsed, edition, footnotes_text):
        if os.environ.get("GRUND_LLM_PROSE", "").lower() not in {"1", "true", "yes"}:
            return prose, None
        if not self.chat.settings.enabled():
            return prose, None
        try:
            draft = self.chat.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "Rewrite the statistical sentence in the same language. "
                            "Use only the numbers in the JSON. Do not add a figure, a year, or a rate."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json_dumps(
                            {
                                "sentence": prose,
                                "value": calculated["primary_raw"],
                                "derived": calculated["derived"],
                                "language": parsed.language,
                                "footnotes": footnotes_text[:500],
                            }
                        ),
                    },
                ]
            )
        except Exception as exc:  # noqa: BLE001
            return prose, {"status": "passed", "certain": False, "rail": "llm_prose", "reason": str(exc)}
        results = self.rails.run(
            "output",
            draft,
            {"language": parsed.language, "allowed": allowed, "refused": False, "source": {"table_id": "x", "retrieved_at": "x", "cells": [1], "api_url": "x"}},
        )
        grounding = next((result for result in results if result.rail == "number_grounding"), None)
        if grounding and grounding.blocked_turn():
            return prose, {
                "status": "modified",
                "certain": True,
                "rail": "number_grounding",
                "reason": "model sentence replaced by the template",
                "categories": grounding.categories,
            }
        return draft.strip(), None

    def _source(self, table, edition, binding, calculated, notes, flags, payload, planner, planner_notes, plan_audit, withheld):
        cells = []
        for row in calculated["rows"]:
            cells.append(
                {
                    "key": row["key"],
                    "labels": row["labels"],
                    "value": row["value"],
                }
            )
        updated = None
        for item in payload.get("metadata") or []:
            if isinstance(item, dict) and item.get("updated"):
                updated = item["updated"]
        return {
            "table_id": table.id,
            "title": edition.title,
            "language": edition.lang,
            "api_url": edition.url,
            "web_url": web_url(edition, table.id),
            "query": binding.selections,
            "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "table_updated": edition.updated or updated,
            "cells": cells,
            "derived": calculated["derived"],
            "footnotes": notes,
            "preliminary": flags["preliminary"],
            "revised": flags["revised"],
            "operation": binding.operation,
            "official_measure": binding.official_measure,
            "notes": binding.notes,
            "planner": planner,
            "planner_notes": planner_notes,
            "plan_audit": plan_audit,
            "footnote_withheld_from_model": withheld,
        }

    def _closed_historical(self, stated_id, other_id) -> bool:
        """The stated table is the Sögulegar copy, and the other table runs past its end."""
        from grund.rerank import _fact

        def lookup(table_id):
            if not table_id:
                return None
            stem = str(table_id)
            if not stem.endswith(".px"):
                stem = stem + ".px"
            return self.catalogue.by_id.get(stem)

        stated = lookup(stated_id)
        other = lookup(other_id)
        if stated is None or other is None:
            return False
        left, right = _fact(stated), _fact(other)
        if not left.historical or right.historical:
            return False
        if not left.span or not right.span:
            return False
        return left.span[1] < right.span[1]

    def _blocked(self, side: str, text: str, context: dict, rail_log: list) -> dict | None:
        results = self.rails.run(side, text, context)
        rail_log.extend(result.to_dict() for result in results)
        for result in results:
            if result.blocked_turn():
                return result.to_dict()
        return None

    def _gated(self, question: str, parsed: ParsedQuestion, chosen: dict, other: dict, gate: str) -> dict:
        from grund.calibrate import feature_row

        chosen = dict(chosen)
        source = dict(chosen.get("source") or {})
        source["gate"] = gate
        source["other_table"] = other.get("table_id")
        source["other_value"] = other.get("value")
        source["other_detail"] = other.get("detail")
        source["other_refused"] = bool(other.get("refused")) or other.get("value") in (None, "")
        source["closed_historical"] = self._closed_historical(chosen.get("table_id"), other.get("table_id"))
        chosen["source"] = source
        chosen["path_pair"] = _path_pair(chosen, other)
        index_table = None
        try:
            hits, _bindings = self._lang_shortlist(question, k=1)
            from grund.topic_prior import maybe_topic_prior

            hits = maybe_topic_prior(self.catalogue, question, hits or [])
            from grund.topicmap import rerank

            hits = rerank(self.catalogue, question, hits or [], parsed.language)
            if hits:
                index_table = hits[0].table.id
        except Exception:
            index_table = None
        # Both paths recomputed the same sex gap. The index rank is a table
        # vote, not a third subtraction, so it does not veto that figure.
        if _sexdiff_agreed(chosen, other):
            index_table = chosen.get("table_id")
        source["index_table"] = index_table
        chosen["source"] = source
        chosen["features"] = feature_row(question, chosen, [other], index_table)
        if getattr(self, "_defer_present", False):
            return chosen
        return self._maybe_abstain(parsed, chosen)

    def _maybe_abstain(self, parsed: ParsedQuestion, result: dict) -> dict:
        from grund.calibrate import should_abstain
        from grund.bind2 import echo_reason, veto_reason

        if result.get("refused"):
            return result
        from grund.istrade import trade_must_refuse
        from grund.ispop import open_age_is_total

        from grund.level_change import mismatch

        if mismatch(parsed.text, result):
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail="level against change",
                planner="level-change",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        from grund.measure_guard import blocks

        if blocks(parsed.text, result):
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail="measure does not match",
                planner="measure-guard",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        from grund.unemp_guard import reason as unemp_reason

        unemp = unemp_reason(parsed.text, result)
        if unemp:
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail=unemp,
                planner="unemp-guard",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        from grund.subgroup_guard import guard_reason as subgroup_guard_reason

        subgroup = subgroup_guard_reason(self, parsed, result)
        if subgroup:
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail=subgroup,
                planner="subgroup-guard",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        if trade_must_refuse(parsed.text, parsed.language) or open_age_is_total(parsed.text, result):
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail="not one published cell",
                planner="kang-refuse",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        from grund.isguard import guard_reason

        blocked = guard_reason(parsed.text, result)
        if blocked:
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail=blocked,
                planner="kang-guard",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        from grund.redteam2 import maybe_correct

        corrected = maybe_correct(self, parsed, result)
        if isinstance(corrected, dict):
            return corrected
        if isinstance(corrected, str):
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail=corrected,
                planner="redteam2",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        from grund.redteam3 import maybe_correct as maybe_correct3

        corrected3 = maybe_correct3(self, parsed, result)
        if isinstance(corrected3, dict):
            return corrected3
        if isinstance(corrected3, str):
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail=corrected3,
                planner="redteam3",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        from grund.urban_age import refuse_reason as urban_age_reason

        urban = urban_age_reason(parsed.text, result)
        if urban:
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail=urban,
                planner="urban-age",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        from grund.sibling import adjust as sibling_adjust

        moved = sibling_adjust(self, parsed, result)
        if isinstance(moved, dict):
            moved["elapsed_ms"] = result.get("elapsed_ms")
            moved["features"] = result.get("features")
            moved["path_pair"] = result.get("path_pair")
            return moved
        from grund.subject_veto import zero_count_reason

        if zero_count_reason(result):
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail="zero count",
                planner="zero-count",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        from grund.compound import split_question

        split = split_question(parsed.text)
        stems = []
        for table_id in list(result.get("tables") or []) + [result.get("table_id")]:
            stem = str(table_id or "").removesuffix(".px")
            if stem and stem not in stems:
                stems.append(stem)
        if split is not None and split[0] == "pair" and len(stems) < 2:
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail="one-table-pair",
                planner="pair",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        echo = echo_reason(parsed.text, result)
        if echo:
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail=echo,
                planner="bind2-echo",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["veto"] = echo
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        from grund.lookalike_gate import lookalike_reason

        likeness = lookalike_reason(self.catalogue, parsed.text, parsed.language, result)
        if likeness:
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail=likeness,
                planner="lookalike",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        from grund.subgroup_bind import bind_reason

        missed = bind_reason(parsed.text, result)
        if missed:
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail=missed,
                planner="subgroup-bind",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["veto"] = missed
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        from grund.loose_gate import loose_gate_reason

        loose = loose_gate_reason(self.catalogue, parsed.text, parsed.language, result)
        if loose:
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail=loose,
                planner="loose-gate",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["veto"] = loose
            refused["features"] = result.get("features")
            refused["path_pair"] = result.get("path_pair")
            return refused
        reason = veto_reason(parsed.text, result)
        if reason:
            refused = self._finish_refusal(
                parsed,
                "no_table",
                list(result.get("rails") or []),
                time.perf_counter(),
                list(result.get("candidates") or []),
                detail=reason,
                planner="bind2-veto",
            )
            refused["elapsed_ms"] = result.get("elapsed_ms")
            refused["veto"] = reason
            return refused
        if os.environ.get("GRUND_TOTAL_CELL", "").strip() == "1":
            from grund_rails.cell_claim import total_cell_keeps

            source = result.get("source") if isinstance(result.get("source"), dict) else {}
            other_silent = bool(source.get("other_refused")) or source.get("other_value") in (None, "")
            if other_silent and source.get("other_table") is None and total_cell_keeps(parsed.text, result):
                source = dict(source)
                source["total_cell"] = True
                result["source"] = source
        abstain, chance = should_abstain(result.get("features"))
        result = dict(result)
        result["calibrator_p"] = chance
        reason = "calibrator" if abstain else None
        if reason is None:
            from grund.frame import current_frame

            frame = current_frame()
            source = result.get("source") if isinstance(result.get("source"), dict) else {}
            if (
                frame is not None
                and frame.use
                and _paths_agreed(result, source)
                and _table_preference(self.catalogue, frame, result) >= 0
            ):
                source = dict(source)
                source["lookalike_resolved"] = True
                result["source"] = source
            from grund.abstain_rule import abstain_reason, score_of

            if result.get("calibrator_p") is None:
                result["calibrator_p"] = score_of(result)
            reason = abstain_reason(result)
        if reason is None:
            return result
        sources = []
        if result.get("table_id"):
            card = result.get("source") if isinstance(result.get("source"), dict) else {}
            url = str(card.get("web_url") or card.get("api_url") or "")
            title = str(card.get("title") or result.get("table_id") or "")
            if not url:
                claims = result.get("claims") or []
                if claims and (claims[0].get("cells") or []):
                    cell = claims[0]["cells"][0]
                    url = str(cell.get("web_url") or cell.get("api_url") or "")
                    title = str(cell.get("title") or title)
            sources.append(
                {
                    "table_id": result.get("table_id"),
                    "title": title,
                    "url": url,
                    "web_url": url,
                }
            )
        sources.extend(item for item in (result.get("candidates") or []) if isinstance(item, dict))
        refused = self._finish_refusal(
            parsed,
            "no_table",
            list(result.get("rails") or []),
            0,
            sources,
            detail=reason,
            planner="calibrator" if reason == "calibrator" else "abstain",
            sources=sources,
        )
        refused["calibrator_p"] = chance
        refused["features"] = result.get("features")
        refused["path_pair"] = result.get("path_pair")
        return refused

    def _agree_with_hybrid(self, question: str, parsed: ParsedQuestion, ranker: dict, rail_log: list, started: float) -> dict:
        """State a figure only when the ranker and hybrid can live with it."""
        from grund.toolpath import _same_number, decide_gate, run_hybrid_safe
        from grund_rails.cell_claim import question_match_claims

        hybrid = run_hybrid_safe(self, question, parsed, [], started)
        from grund.judgesim_fix import enabled as judgesim_enabled
        from grund.judgesim_fix import gate_choice

        ranker_match = question_match_claims(question, ranker.get("claims") or [])
        hybrid_match = question_match_claims(question, hybrid.get("claims") or [])
        narrow = False
        if _rc1_on() and not _asks_constant(question):
            # A constant-price sibling is not the cell the current-price path read.
            ranker_const = _constant_price_result(ranker)
            hybrid_const = _constant_price_result(hybrid)
            if ranker_const and not hybrid_const and hybrid_match:
                ranker_match = False
                narrow = True
            elif hybrid_const and not ranker_const and ranker_match:
                hybrid_match = False
                narrow = True
        if _rc1_on() and _change_kept(ranker, hybrid_match, hybrid):
            narrow = True
        elif _rc1_on() and _change_kept(hybrid, ranker_match, ranker):
            narrow = True
        if judgesim_enabled():
            # The tighter check is the measure match plus level-versus-change
            # and current-versus-constant prices. It does not replace that match.
            choice = gate_choice(question, ranker, hybrid)
            sole = False
        else:
            choice = decide_gate(
                _same_number(ranker.get("value"), hybrid.get("value")),
                ranker_match,
                hybrid_match,
            )
            sole = narrow and choice in {"ranker", "hybrid"} and (ranker_match != hybrid_match)
        if choice not in {"ranker", "hybrid"} and _rc3_on():
            picked = _rc3_choice(question, ranker, hybrid)
            if picked:
                choice = picked
                sole = True
        from grund.frame import current_frame

        framed = current_frame()
        if framed is not None and framed.use and _same_number(ranker.get("value"), hybrid.get("value")):
            ranker_pref = _table_preference(self.catalogue, framed, ranker)
            hybrid_pref = _table_preference(self.catalogue, framed, hybrid)
            if hybrid_pref > ranker_pref:
                choice = "hybrid"
            elif ranker_pref > hybrid_pref:
                choice = "ranker"
        from grund.series_prefer import capital_guard, preferred_path

        guard = capital_guard(question, ranker, hybrid)
        if guard == "refuse":
            refused = self._finish_refusal(
                parsed,
                "no_table",
                rail_log,
                started,
                [],
                detail="the capital is Reykjavík, not the capital region",
                planner="series-pick",
            )
            refused["path_pair"] = _path_pair(ranker, hybrid)
            return refused
        side = guard if guard in {"ranker", "hybrid"} else preferred_path(question, ranker, hybrid)
        if side in {"ranker", "hybrid"}:
            chosen = ranker if side == "ranker" else hybrid
            other = hybrid if side == "ranker" else ranker
            chosen = dict(chosen)
            source = dict(chosen.get("source") or {})
            source["lookalike_resolved"] = True
            source["series_pick"] = side
            chosen["source"] = source
            return self._gated(question, parsed, chosen, other, side)
        from grund.iscover import cover_ranker

        covered = cover_ranker(question, parsed.language, ranker)
        if covered is not None:
            # The ranker cell is the named year of age. Keep it even when the
            # hybrid path states the all-ages total, and do not abstain on that split.
            return self._gated(question, parsed, covered, hybrid, "is-cover")
        from grund.istown import town_ranker

        town = town_ranker(question, parsed.language, ranker)
        if town is not None:
            return self._gated(question, parsed, town, hybrid, "is-town")
        from grund.isjobs import job_ranker

        job = job_ranker(question, parsed.language, ranker)
        if job is not None:
            # The ranker cell is the asked labour-force measure. Keep it when
            # the hybrid path states a different series, and do not abstain on that split.
            return self._gated(question, parsed, job, hybrid, "is-jobs")
        from grund.isshare import share_ranker

        shared = share_ranker(question, parsed.language, ranker)
        if shared is not None:
            return self._gated(question, parsed, shared, hybrid, "is-share")
        from grund.isjobsex import jobsex_ranker

        jobsex = jobsex_ranker(question, parsed.language, ranker)
        if jobsex is not None:
            return self._gated(question, parsed, jobsex, hybrid, "is-jobsex")
        from grund.isbirths import births_ranker

        births = births_ranker(question, parsed.language, ranker)
        if births is not None:
            return self._gated(question, parsed, births, hybrid, "is-births")
        from grund.isregion import region_ranker

        region = region_ranker(question, parsed.language, ranker)
        if region is not None:
            return self._gated(question, parsed, region, hybrid, "is-region")
        from grund.isgdp import gdp_ranker

        gdp = gdp_ranker(question, parsed.language, ranker)
        if gdp is not None:
            return self._gated(question, parsed, gdp, hybrid, "is-gdp")
        from grund.istrade import trade_ranker

        traded = trade_ranker(question, parsed.language, ranker)
        if traded is not None:
            return self._gated(question, parsed, traded, hybrid, "is-trade")
        from grund.iscpi import cpi_ranker

        priced = cpi_ranker(question, parsed.language, ranker)
        if priced is not None:
            return self._gated(question, parsed, priced, hybrid, "is-cpi")
        from grund.iswage import wage_ranker

        waged = wage_ranker(question, parsed.language, ranker)
        if waged is not None:
            return self._gated(question, parsed, waged, hybrid, "is-wage")
        from grund.isstays import stays_ranker

        stayed = stays_ranker(question, parsed.language, ranker)
        if stayed is not None:
            return self._gated(question, parsed, stayed, hybrid, "is-stays")
        from grund.isquarter import quarter_ranker

        quartered = quarter_ranker(question, parsed.language, ranker)
        if quartered is not None:
            return self._gated(question, parsed, quartered, hybrid, "is-quarter")
        from grund.isorigin import origin_ranker

        originated = origin_ranker(question, parsed.language, ranker)
        if originated is not None:
            return self._gated(question, parsed, originated, hybrid, "is-origin")
        from grund.isbuilding import building_ranker

        built = building_ranker(question, parsed.language, ranker)
        if built is not None:
            return self._gated(question, parsed, built, hybrid, "is-building")
        from grund.ispop import pop_ranker

        nation = pop_ranker(question, parsed.language, ranker)
        if nation is not None:
            return self._gated(question, parsed, nation, hybrid, "is-pop")
        if choice == "ranker":
            # Same figure: keep the series that is not a breakdown table.
            if (
                _same_number(ranker.get("value"), hybrid.get("value"))
                and _breakdown_title(ranker)
                and not _breakdown_title(hybrid)
            ):
                choice = "hybrid"
                sole = False
            else:
                return self._gated(question, parsed, _mark_sole(ranker, sole), hybrid, "ranker")
        if choice == "hybrid":
            return self._gated(question, parsed, _mark_sole(hybrid, sole), ranker, "hybrid")
        from grund.keep_gate import path_to_keep

        kept = path_to_keep(self.catalogue, question, parsed.language, ranker, hybrid)
        if kept is not None:
            chosen, other = kept
            chosen = dict(chosen)
            source = dict(chosen.get("source") or {})
            source["lookalike_resolved"] = True
            chosen["source"] = source
            return self._gated(question, parsed, chosen, other, "keep")
        links = []
        for result in (ranker, hybrid):
            for item in list(result.get("candidates") or []) + list((result.get("source") or {}).get("sources") or []):
                if isinstance(item, dict) and item not in links:
                    links.append(item)
            if result.get("table_id"):
                card = result.get("source") if isinstance(result.get("source"), dict) else {}
                links.append(
                    {
                        "table_id": result.get("table_id"),
                        "title": card.get("title") or result.get("table_id"),
                        "url": card.get("web_url") or card.get("api_url") or "",
                        "web_url": card.get("web_url") or card.get("api_url") or "",
                        "reason": "disagreed",
                    }
                )
        refused = self._finish_refusal(
            parsed,
            "no_table",
            rail_log,
            started,
            links,
            detail="the ranker and the hybrid path did not agree",
            planner="gate",
            sources=links,
        )
        refused["path_pair"] = _path_pair(ranker, hybrid)
        return refused

    def _finish_refusal(
        self,
        parsed,
        kind,
        rail_log,
        started,
        candidates,
        detail=None,
        planner=None,
        sources=None,
    ) -> dict:
        if kind == "injection":
            refusal_kind = "injection"
        elif kind == "clarify_month":
            refusal_kind = "clarify_month"
        elif kind == "clarify":
            refusal_kind = "clarify"
        elif kind == "out_of_scope":
            refusal_kind = "out_of_scope"
        else:
            refusal_kind = "no_table"
        text = refusal(parsed.language, refusal_kind)
        if detail and kind != "injection":
            # Detail can contain codes and counts. Keep it off the sentence so a
            # refusal cannot smuggle a figure. It is returned beside the answer.
            pass
        output = self.rails.run(
            "output",
            text,
            {
                "question": parsed.text,
                "language": parsed.language,
                "refused": True,
                "clarify": kind in {"clarify", "clarify_month"},
                "allowed": [],
                "source": None,
            },
        )
        rail_log.extend(result.to_dict() for result in output)
        if any(result.blocked_turn() for result in output):
            text = refusal(parsed.language, "no_table")
        # Table ids and links contain digits. They are attached after the rail,
        # which would otherwise treat VIS01000 as a figure and drop the citation.
        from grund.answer import refusal_sources

        extra = refusal_sources(parsed.language, sources or candidates)
        if extra:
            text = text.rstrip() + " " + extra
        return {
            "answer": text,
            "refused": True,
            "clarify": kind in {"clarify", "clarify_month"},
            "language": parsed.language,
            "value": None,
            "value_display": None,
            "table_id": None,
            "tables": [],
            "operation": None,
            "source": None,
            "rails": rail_log,
            "candidates": candidates,
            "sources": list(sources or []),
            "detail": detail,
            "planner": planner,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }


def _cards_from_bindings(hits: list[Hit], parsed: ParsedQuestion, value_bindings: dict) -> list:
    """Shortlist cards whose codes are exactly the bind_values choices."""
    cards = []
    for hit in hits:
        if len(cards) >= 5:
            break
        choices = value_bindings.get(hit.table.id) or []
        if not choices:
            continue
        edition = hit.table.edition(parsed.language) or hit.table.edition("en")
        if edition is None:
            continue
        grouped: dict[str, list[tuple[str, str]]] = {}
        for choice in choices:
            bucket = grouped.setdefault(choice.variable_code, [])
            pair = (choice.value_code, choice.value_label)
            if pair not in bucket:
                bucket.append(pair)
        variables = []
        for variable in edition.variables:
            values = grouped.get(variable.code)
            if values:
                variables.append((variable, values))
        if variables:
            cards.append((hit.table.id, edition, variables))
    return cards


def _quoted_len(parsed: ParsedQuestion, binding: Binding) -> int:
    stem = _series_stem(binding.edition.title)
    if len(stem) >= 20 and stem in parsed.folded:
        return len(stem)
    return 0


def _series_stem(title: str) -> str:
    folded = re.sub(r"\b(?:19|20)\d{2}\b", " ", fold(title))
    return re.sub(r"\s+", " ", folded).strip(" -")


def _specific_labels(binding: Binding, parsed: ParsedQuestion) -> set[str]:
    found = set()
    query = set(parsed.query_tokens)
    for entry in binding.selections:
        variable = binding.edition.variable(entry["code"])
        if variable is None or variable.time:
            continue
        for code in entry["selection"]["values"]:
            for token in tokens(variable.label(code)):
                if len(token) >= 6 and token in query and token not in _PLACE_SKIP:
                    found.add(token)
    return found


def _total_code(edition: Edition, variable_code: str) -> str | None:
    variable = edition.variable(variable_code)
    if variable is None:
        return None
    for code, label in variable.values:
        if fold(label) == "total" or fold(code) == "total":
            return code
    return None


def _code_by_label(edition: Edition, variable_code: str, label_folded: str) -> str | None:
    variable = edition.variable(variable_code)
    if variable is None:
        return None
    for code, label in variable.values:
        if fold(label) == label_folded:
            return code
    return None


def _card(table_id: str, edition: Edition, parsed: ParsedQuestion) -> dict:
    query = set(parsed.query_tokens)
    variables = []
    for variable in edition.variables:
        ranked = []
        for code, label in variable.values:
            overlap = len(set(tokens(label)) & query)
            ranked.append((overlap, code, label))
        ranked.sort(key=lambda item: item[0], reverse=True)
        keep = ranked[:18]
        if variable.time:
            keep = ranked[:4] + ranked[-4:]
        variables.append(
            {
                "code": variable.code,
                "text": variable.text,
                "time": variable.time,
                "values": [{"code": code, "text": label} for _score, code, label in keep],
            }
        )
    return {"id": table_id, "title": edition.title, "variables": variables}


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


def json_error():
    import json

    return json.JSONDecodeError
