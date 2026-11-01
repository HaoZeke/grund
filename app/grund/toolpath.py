"""Optional answer paths. The default remains the metadata ranker.

``GRUND_PATH=tools`` runs the NLP parse-then-tools path. It is not the
default: on its own it covers far less than the ranker. ``GRUND_PATH=hybrid``
takes the ranker's top 20 tables, then uses the tool steps to map filters,
set totals, POST, and apply the operation. CellClaimRail, including the
measure check, decides. A block moves to the next mapped table, up to four,
and then the answer is a refusal with links.
"""

from __future__ import annotations

import os
from typing import Any

from grund.arithmetic import format_stat
from grund.parse import ParsedQuestion


class PathError(RuntimeError):
    """GRUND_PATH is not one of the paths this process knows."""


def answer_path() -> str:
    raw = os.environ.get("GRUND_PATH", "ranker").strip().lower()
    if raw in {"", "ranker", "current", "default"}:
        return "ranker"
    if raw in {"tools", "hybrid", "index"}:
        return raw
    raise PathError(
        f"GRUND_PATH={raw!r} is not a path. "
        "Use ranker (the default), index, tools, or hybrid."
    )


def dispatch(engine, question: str, parsed: ParsedQuestion, rail_log: list, started: float) -> dict | None:
    mode = answer_path()
    if mode == "ranker":
        return None
    engine._require_value_index()
    if mode == "index":
        return None
    if mode == "tools":
        return run_tools(engine, question, parsed, rail_log, started)
    return run_hybrid(engine, question, parsed, rail_log, started)


def edition_payload(edition) -> dict:
    variables = []
    for variable in edition.variables:
        variables.append(
            {
                "code": variable.code,
                "text": variable.text,
                "time": bool(variable.time),
                "elimination": bool(variable.elimination),
                "values": [(str(code), str(label)) for code, label in variable.values],
            }
        )
    return {
        "url": edition.url,
        "title": edition.title,
        "path_texts": list(edition.path_texts or []),
        "updated": edition.updated or "",
        "variables": variables,
    }


def decide_gate(same: bool, ranker_match: bool, hybrid_match: bool) -> str:
    """Which answer the agreement gate may state.

    A cell is usable when it passes every question-match check. Both
    usable and the same figure: the ranker. They disagree and only one is
    usable: that one. Both usable, or neither: a refusal with the links.
    """
    if ranker_match and hybrid_match and same:
        return "ranker"
    if ranker_match and hybrid_match:
        return "refuse"
    if ranker_match:
        return "ranker"
    if hybrid_match:
        return "hybrid"
    return "refuse"


def _stated(result: dict | None) -> bool:
    if not result or result.get("refused"):
        return False
    return result.get("value") not in (None, "")


def _same_number(left, right) -> bool:
    try:
        a = float(str(left).replace(",", "").replace(" ", ""))
        b = float(str(right).replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


def _measure_ok(question: str, result: dict | None) -> bool:
    if not _stated(result):
        return False
    claims = result.get("claims") or []
    if not claims:
        return True
    from grund_rails.cell_claim import _measure_block

    claim = claims[0]
    return _measure_block(question, claim, claim.get("cells") or []) is None


def run_hybrid_safe(engine, question: str, parsed: ParsedQuestion, rail_log: list, started: float) -> dict:
    """Hybrid. A missing value index is a startup failure, not a quiet refusal.

    The caller runs this after the ranker, including when the ranker claim
    was blocked. Swallowing IndexOffline there used to skip hybrid and state
    the ranker figure alone.
    """
    engine._require_value_index()
    return run_hybrid(engine, question, parsed, rail_log, started)


def run_tools(engine, question: str, parsed: ParsedQuestion, rail_log: list, started: float) -> dict:
    from pathlib import Path

    from grund_lang.pxtools import MetaStore, answer

    root = Path(__file__).resolve().parents[2]
    tables = os.environ.get("GRUND_TABLES", str(root / "data" / "index" / "tables.jsonl.gz"))
    if getattr(engine, "_meta_path", None) != tables:
        engine._meta_store = MetaStore(tables)
        engine._meta_path = tables
    live = os.environ.get("GRUND_TOOLS_LIVE", "").strip().lower() in {"1", "true", "yes"}
    result = answer(
        question,
        engine._meta_store,
        engine.client,
        ranker=_ranker(engine),
        live=live,
        mode="tools",
    )
    if result.get("refused") or not result.get("cells"):
        bound = _bind_candidates(engine, question, parsed, result.get("candidates") or [], rail_log, started, path="tools")
        if bound is not None:
            return bound
    return _adopt(engine, question, parsed, result, rail_log, started, path="tools")


def run_hybrid(engine, question: str, parsed: ParsedQuestion, rail_log: list, started: float) -> dict:
    """Ranker shortlist, then the tool mapper, then the cell-claim rail."""
    from grund.sexdiff import binding_for, is_sex_difference

    if is_sex_difference(question):
        # Same cells as the ranker. The two paths then agree on the sex gap.
        hits, _bindings = engine._lang_shortlist(question, k=20)
        forced = binding_for(engine.catalogue, parsed, question, hits or [])
        if forced is None:
            return engine._finish_refusal(
                parsed, "no_table", rail_log, started, candidates=[], detail="sex difference", planner="hybrid"
            )
        binding, table = forced
        produced = engine._produce(parsed, binding, table, question, rail_log)
        if not produced.get("ok"):
            return engine._finish_refusal(
                parsed,
                "no_table",
                rail_log,
                started,
                candidates=[],
                detail=produced.get("detail"),
                planner="hybrid",
            )
        from grund.engine import _guard_verdict

        verdict = _guard_verdict(question, parsed, produced)
        rail_log.append(verdict)
        from grund_rails.cell_claim import question_match_claims, rail_effect

        passed = verdict.get("status") == "passed" and verdict.get("certain") is not False
        effect = "pass" if passed else rail_effect(verdict.get("reason"), verdict.get("categories"), computed=True)
        claims = produced.get("claims") or []
        if effect == "pass" and not question_match_claims(question, claims):
            effect = "retry"
            verdict = {
                **verdict,
                "status": "blocked",
                "reason": "cited cell does not match the question",
                "categories": ["unsupported_cell"],
            }
        if effect != "pass" or not claims:
            return engine._finish_refusal(
                parsed,
                "no_table",
                rail_log,
                started,
                candidates=[],
                detail=verdict.get("reason") or produced.get("detail"),
                planner="hybrid",
            )
        return _state(engine, parsed, claims[0], produced["prose"], verdict, rail_log, started, [], path="hybrid")
    from grund_lang.pxtools import _claim_from_payload, _post, map_request, web_url
    from grund_lang.request import ParseError, parse_request

    # The language-index shortlist is not the catalogue list. Reordering it
    # knocks gold tables off rank 1, so the look-alike stage stays off here.
    hits, _bindings = engine._lang_shortlist(question, k=20)
    from grund.frame import current_frame, order_hits
    from grund.topic_prior import maybe_topic_prior

    hits = maybe_topic_prior(engine.catalogue, question, hits or [])
    hits = order_hits(engine.catalogue, hits, current_frame())
    from grund.topicmap import rerank

    hits = rerank(engine.catalogue, question, hits or [], parsed.language)
    from grund.agree_hyb import enabled as agree_hyb

    from grund_index.textutil import fold as _fold_q

    asked_place = _fold_q(question)
    if (
        agree_hyb()
        and hits is not None
        and parsed.operation == "level"
        and ("hofudborg" in asked_place or ("capital" in asked_place and "region" in asked_place))
    ):
        # The catalogue ranker can hold the table the language list missed.
        # Trying that table does not reorder the language list.
        from grund.rerank import maybe_rerank, search_k

        years = [year for year, _month in parsed.periods]
        found = maybe_rerank(
            engine.catalogue,
            question,
            engine.catalogue.search(question, k=search_k(), years=years),
            years,
        )
        seen = {hit.table.id for hit in hits}
        hits = list(hits)
        for hit in found:
            if hit.table.id not in seen:
                hits.append(hit)
                seen.add(hit.table.id)
    if not hits:
        return engine._finish_refusal(
            parsed, "no_table", rail_log, started, candidates=[], detail="no shortlist", planner="hybrid"
        )
    try:
        request = parse_request(question)
    except ParseError:
        request = None
    links: list[dict] = []
    checked = 0
    language = parsed.language or (request or {}).get("_language") or "en"
    from grund.subject_veto import enabled as subject_enabled
    from grund.subject_veto import search_leader_title, subject_gap

    leader_title = ""
    if subject_enabled():
        leader_title = search_leader_title(
            engine.catalogue, question, language, [year for year, _month in parsed.periods]
        )
    shared_answer = _answer_shared(engine, question, parsed, hits, rail_log, started, language)
    if shared_answer is not None:
        return shared_answer
    for hit in hits:
        if checked >= 4:
            break
        edition = hit.table.edition(language) or hit.table.edition("en")
        if edition is None:
            continue
        table_id = hit.table.id.removesuffix(".px")
        link = {"table_id": table_id, "api_url": edition.url, "web_url": web_url(edition.url), "title": edition.title}
        from grund.frame import current_frame as _frame_now

        active = _frame_now()
        if subject_gap(question, leader_title, edition.title) and not (
            active is not None and active.preference(hit.table) >= 20
        ):
            links.append({**link, "reason": "subject"})
            continue
        if active is not None and active.use:
            bound = _bind_hit(engine, question, parsed, hit, edition, rail_log, started, path="hybrid")
            if bound is not None and not bound.get("refused"):
                return bound
            if bound is not None:
                checked += 1
            links.append({**link, "reason": (bound or {}).get("detail") or "filters did not map"})
            if bound and bound.get("transport"):
                break
            continue
        from grund.agree_hyb import constant_price_title, enabled as agree_hyb
        from grund.agree_hyb import labour_title_for_headcount, quarterly_gdp_title

        if constant_price_title(edition.title, question):
            links.append({**link, "reason": "constant prices"})
            continue
        if agree_hyb() and quarterly_gdp_title(edition.title, question):
            links.append({**link, "reason": "quarterly gdp"})
            continue
        if agree_hyb() and labour_title_for_headcount(edition.title, question):
            links.append({**link, "reason": "labour table"})
            continue
        mapped_request = dict(request) if request is not None else None
        if mapped_request is not None:
            mapped_request["_question"] = question
        mapped = map_request(edition_payload(edition), mapped_request) if mapped_request is not None else None
        if mapped is not None:
            from grund.topic_prior import named_cells

            for variable, code in named_cells(edition, question):
                mapped[variable] = [code]
        if mapped is None:
            bound = _bind_hit(engine, question, parsed, hit, edition, rail_log, started, path="hybrid")
            if bound is not None:
                if bound.get("refused"):
                    links.append({**link, "reason": bound.get("detail") or "binder did not pass the rail"})
                    if bound.get("transport"):
                        break
                    continue
                return bound
            links.append({**link, "reason": "filters did not map"})
            continue
        payload = _post(engine.client, edition.url, mapped)
        claim = _claim_from_payload(table_id, edition_payload(edition), mapped, payload, request)
        if claim is None:
            links.append({**link, "reason": "the query returned no usable cells"})
            continue
        checked += 1
        _stamp(claim, edition, question)
        prose = _sentence(parsed.language, claim["value"])
        verdict = _guard(question, parsed, claim, prose)
        rail_log.append(verdict)
        from grund_rails.cell_claim import rail_effect

        passed = verdict.get("status") == "passed" and verdict.get("certain") is not False
        effect = "pass" if passed else rail_effect(verdict.get("reason"), verdict.get("categories"), computed=True)
        if effect == "pass":
            from grund_rails.cell_claim import question_match_claims

            if not question_match_claims(question, [claim]):
                effect = "retry"
                verdict = {
                    **verdict,
                    "status": "blocked",
                    "reason": "cited cell does not match the question",
                    "categories": ["unsupported_cell"],
                }
        if effect == "pass":
            return _state(engine, parsed, claim, prose, verdict, rail_log, started, links, path="hybrid")
        reason = verdict.get("reason") or "cell claim blocked"
        links.append({**link, "reason": reason})
        if effect != "retry":
            break
    return engine._finish_refusal(
        parsed,
        "no_table",
        rail_log,
        started,
        candidates=links,
        detail=links[-1]["reason"] if links else "no mapped table",
        planner="hybrid",
        sources=links,
    )


def _answer_shared(engine, question, parsed, hits, rail_log, started, language: str):
    """Post the retied query already stored for this question.

    The ranker ran the retie. This path sends that query, so the two
    answers cannot disagree about the cell.
    """
    from grund.bind2 import enabled, shared_binding
    from grund.engine import _guard_verdict

    if not enabled():
        return None
    for hit in hits:
        edition = hit.table.edition(language) or hit.table.edition("en")
        if edition is None:
            continue
        binding = shared_binding(question, edition, hit.table.id)
        if binding is None:
            continue
        produced = engine._produce(parsed, binding, hit.table, question, rail_log)
        if not produced.get("ok"):
            return None
        verdict = _guard_verdict(question, parsed, produced)
        rail_log.append(verdict)
        passed = verdict.get("status") == "passed" and verdict.get("certain") is not False
        claims = produced.get("claims") or []
        if not passed or not claims:
            return None
        from grund_rails.cell_claim import question_match_claims

        if not question_match_claims(question, claims):
            return None
        return _state(engine, parsed, claims[0], produced["prose"], verdict, rail_log, started, [], path="hybrid")
    return None


def _bind_hit(engine, question, parsed, hit, edition, rail_log, started, path: str):
    """The catalogue binder, when the tool mapper cannot name a code."""
    from grund.bind import bind
    from grund.engine import _guard_verdict
    from grund.validator import ValidationError, validate

    binding = bind(edition, parsed)
    if binding is None:
        return None
    if path == "hybrid":
        from grund.agree_hyb import enabled as agree_hyb
        from grund.agree_hyb import place_selection

        if agree_hyb():
            picked = place_selection(question, edition_payload(edition)["variables"], parsed.operation)
            if picked is None:
                return None
            seen: set[str] = set()
            for entry in binding.selections:
                code = str(entry.get("code"))
                seen.add(code)
                if code not in picked:
                    continue
                selection = entry.setdefault("selection", {})
                selection["filter"] = "item"
                selection["values"] = list(picked[code])
            for code, values in picked.items():
                if code in seen:
                    continue
                binding.selections.append(
                    {"code": code, "selection": {"filter": "item", "values": list(values)}}
                )
    try:
        validate(edition, binding.selections)
    except ValidationError:
        return None
    produced = engine._produce(parsed, binding, hit.table, question, rail_log)
    if not produced.get("ok"):
        return {
            "refused": True,
            "detail": produced.get("detail"),
            "transport": produced.get("transport"),
        }
    verdict = _guard_verdict(question, parsed, produced)
    rail_log.append(verdict)
    passed = verdict.get("status") == "passed" and verdict.get("certain") is not False
    claims = produced.get("claims") or []
    if not passed or not claims:
        return {"refused": True, "detail": verdict.get("reason"), "transport": False}
    from grund_rails.cell_claim import question_match_claims

    if not question_match_claims(question, claims):
        return {"refused": True, "detail": "cited cell does not match the question", "transport": False}
    return _state(engine, parsed, claims[0], produced["prose"], verdict, rail_log, started, [], path=path)


def _bind_candidates(engine, question, parsed, candidates, rail_log, started, path: str):
    checked = 0
    for candidate in candidates:
        if checked >= 4:
            break
        table_id = str(candidate.get("table_id") or "")
        if not table_id:
            continue
        if not table_id.endswith(".px"):
            table_id = table_id + ".px"
        table = engine.catalogue.by_id.get(table_id)
        if table is None:
            continue
        edition = table.edition(parsed.language) or table.edition("en")
        if edition is None:
            continue

        class _Hit:
            pass

        hit = _Hit()
        hit.table = table
        bound = _bind_hit(engine, question, parsed, hit, edition, rail_log, started, path=path)
        checked += 1
        if bound is None or bound.get("refused"):
            if bound and bound.get("transport"):
                break
            continue
        return bound
    return None


def _ranker(engine):
    def rank(question: str, k: int = 4):
        index = engine._language_index()
        if index is None:
            return []
        return index.search(question, k=k)

    return rank


def _stamp(claim: dict, edition, question: str) -> None:
    from grund_rails.cell_claim import infer_measure

    latest = ""
    variable = edition.time_variable()
    if variable is not None and variable.values:
        latest = str(variable.values[-1][0])
    claim["measure"] = "share" if claim.get("op") == "share" else infer_measure(question)
    claim["updated"] = str(getattr(edition, "updated", "") or "")
    for cell in claim.get("cells") or []:
        cell["title"] = edition.title
        cell["latest_period"] = latest


def _guard(question: str, parsed: ParsedQuestion, claim: dict, prose: str) -> dict:
    from grund_rails.cell_claim import infer_measure
    from grund_rails.vangrail_client import check_output

    if not claim.get("measure"):
        claim["measure"] = "share" if claim.get("op") == "share" else infer_measure(question)
    periods = []
    for cell in claim.get("cells") or []:
        for value in (cell.get("labels") or {}).values():
            text = str(value)
            if len(text) >= 4 and text[:4].isdigit():
                periods.append(text)
    from grund.frame import current_frame

    payload = current_frame().rail_payload() if current_frame() is not None else {}
    context = {
        "language": parsed.language,
        "question": question,
        "user_input": question,
        "asked": {"periods": periods, "op": claim.get("op"), "named_values": {}, "terms": [], "frame": payload},
        "frame": payload,
        "claims": [claim],
        "computed": True,
    }
    return check_output(prose, question, context)


def _sentence(language: str, value: Any) -> str:
    shown = format_stat(str(value), language or "en")
    if language == "is":
        return f"Talan var {shown}."
    return f"The figure was {shown}."


def _adopt(engine, question, parsed, result: dict, rail_log: list, started: float, path: str) -> dict:
    links = list(result.get("candidates") or [])
    if result.get("refused") or not result.get("cells"):
        return engine._finish_refusal(
            parsed,
            "no_table",
            rail_log,
            started,
            candidates=links,
            detail=result.get("reason"),
            planner=path,
            sources=links,
        )
    prose = _sentence(parsed.language, result.get("value"))
    verdict = _guard(question, parsed, result, prose)
    rail_log.append(verdict)
    from grund_rails.cell_claim import rail_effect

    passed = verdict.get("status") == "passed" and verdict.get("certain") is not False
    effect = "pass" if passed else rail_effect(verdict.get("reason"), verdict.get("categories"), computed=True)
    if effect != "pass":
        links = links or [
            {
                "table_id": (result.get("cells") or [{}])[0].get("table_id"),
                "api_url": (result.get("cells") or [{}])[0].get("api_url"),
                "web_url": (result.get("cells") or [{}])[0].get("web_url"),
                "reason": verdict.get("reason"),
            }
        ]
        return engine._finish_refusal(
            parsed,
            "no_table",
            rail_log,
            started,
            candidates=links,
            detail=verdict.get("reason"),
            planner=path,
            sources=links,
        )
    return _state(engine, parsed, result, prose, verdict, rail_log, started, links, path=path)


def _state(engine, parsed, claim, prose, verdict, rail_log, started, links, path: str) -> dict:
    import time

    cells = claim.get("cells") or []
    table_id = str(cells[0].get("table_id") or "") if cells else ""
    if table_id and not table_id.endswith(".px"):
        table_id = table_id + ".px"
    from grund.answer import source_line

    filters = []
    period = ""
    url = ""
    for cell in cells:
        for key, value in (cell.get("labels") or {}).items():
            if str(key) and str(value) and str(value) not in filters:
                filters.append(str(value))
        if cell.get("period"):
            period = str(cell.get("period"))
        url = str(cell.get("web_url") or cell.get("api_url") or url)
    calculated = str(claim.get("op") or "") in {"difference", "change", "yoy_pct", "pct_change", "share", "sum"}
    prose = prose.rstrip() + " " + source_line(
        parsed.language,
        table_id,
        filters[:6],
        period,
        url,
        str(claim.get("updated") or ""),
        calculated,
    )
    return {
        "answer": prose,
        "refused": False,
        "clarify": False,
        "language": parsed.language,
        "value": claim.get("value"),
        "value_display": format_stat(str(claim.get("value")), parsed.language),
        "table_id": table_id or None,
        "tables": [table_id] if table_id else [],
        "operation": claim.get("op"),
        "planner": path,
        "source": {"planner": path, "path": path, "tool_source": claim.get("source")},
        "claims": [claim],
        "verdict": verdict,
        "retries": sum(1 for item in rail_log if item.get("status") == "blocked"),
        "rails": rail_log,
        "candidates": links,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
