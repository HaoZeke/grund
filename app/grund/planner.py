"""Hybrid planner: a shortlist, a constrained query, then a confidence check.

The model may only emit table ids and value codes from the shortlist. The
grammar is a JSON schema sent to an OpenAI-compatible server that supports
response_format json_schema (llama.cpp does). Arithmetic stays in code.
A low or medium confidence, a refusal, or a query that will not bind falls
back to the deterministic plan.
"""

from __future__ import annotations

from grund.bind import Binding, _match_period, _previous, _value_score, bind, is_total
from grund.parse import ParsedQuestion
from grund_index.catalogue import Hit
from grund_index.model import Edition, Variable

CONFIDENCE = ("low", "medium", "high")
OPERATIONS = ("level", "yoy_pct", "share", "difference", "rebase", "per_capita")

_SYSTEM = (
    "Pick the Statistics Iceland table and the value codes that answer the question. "
    "The program does the arithmetic. "
    "confidence is high when one code on each variable matches the question, "
    "medium when two codes on a variable could both answer it, "
    "and low when you are guessing which table. "
    "Include every listed variable. values are codes. Put the answering code first. "
    "For a share, include the named value and the total on that same variable, and no other codes."
)


def shortlist(hits: list[Hit], parsed: ParsedQuestion, limit: int = 4) -> list[tuple[str, Edition, list[tuple[Variable, list[tuple[str, str]]]]]]:
    cards = []
    for hit in hits:
        if len(cards) >= limit:
            break
        edition = hit.table.edition(parsed.language) or hit.table.edition("en")
        if edition is None:
            continue
        variables = []
        usable = True
        for variable in edition.variables:
            values = candidate_values(variable, parsed)
            if not values and not variable.elimination:
                usable = False
                break
            if values:
                variables.append((variable, values))
        if usable and variables:
            cards.append((hit.table.id, edition, variables))
    return cards


def candidate_values(variable: Variable, parsed: ParsedQuestion) -> list[tuple[str, str]]:
    """Totals, labels that overlap the question, and the periods the question named."""
    values = list(variable.values)
    if not values:
        return []
    if len(values) <= 8:
        return values
    chosen: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(code: str, label: str) -> None:
        if code in seen:
            return
        seen.add(code)
        chosen.append((code, label))

    if variable.time:
        codes = variable.codes()
        for year, month in parsed.periods:
            match = _match_period(codes, year, month)
            if match is None and month is not None:
                match = _match_period(codes, year, None)
            if match is None:
                continue
            add(match, variable.label(match))
            if parsed.operation in {"yoy_pct", "difference"}:
                previous = _previous(codes, match)
                if previous:
                    add(previous, variable.label(previous))
        if parsed.rebase_year is not None:
            base = _match_period(codes, parsed.rebase_year, None)
            if base:
                add(base, variable.label(base))
        if not chosen:
            for code, label in values[-3:]:
                add(code, label)
        return chosen

    for code, label in values:
        if is_total(label):
            add(code, label)
    query = set(parsed.query_tokens)
    ranked = []
    for code, label in values:
        if is_total(label):
            continue
        score, overlap = _value_score(query, parsed.folded, label)
        if score > 0:
            ranked.append((score, overlap, code, label))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _score, _overlap, code, label in ranked[:8]:
        add(code, label)
    if not chosen:
        add(values[0][0], values[0][1])
    return chosen[:12]


def query_schema(cards: list[tuple[str, Edition, list]], parsed: ParsedQuestion) -> dict:
    branches = []
    for table_id, _edition, variables in cards:
        properties = {}
        required = []
        for variable, values in variables:
            codes = [code for code, _label in values]
            if variable.time:
                cap = 3 if parsed.operation in {"yoy_pct", "difference", "rebase"} else 1
            elif parsed.operation == "share":
                cap = 2
            else:
                cap = 1
            properties[variable.code] = {
                "type": "array",
                "minItems": 1,
                "maxItems": min(cap, len(codes)),
                "items": {"type": "string", "enum": codes},
            }
            required.append(variable.code)
        branches.append(
            {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["query"]},
                    "confidence": {"type": "string", "enum": list(CONFIDENCE)},
                    "table_id": {"type": "string", "enum": [table_id]},
                    "selections": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    },
                },
                "required": ["action", "confidence", "table_id", "selections"],
                "additionalProperties": False,
            }
        )
    return {"oneOf": branches}


def render_shortlist(parsed: ParsedQuestion, cards: list[tuple[str, Edition, list]]) -> str:
    lines = [
        f"Question: {parsed.text}",
        f"Arithmetic the program will apply: {parsed.operation}",
    ]
    for table_id, edition, variables in cards:
        lines.append(f"\n{table_id} | {edition.title}")
        for variable, values in variables:
            pairs = "; ".join(f"{code}={label}" for code, label in values)
            kind = "time" if variable.time else variable.text
            lines.append(f"  {variable.code} ({kind}): {pairs}")
    return "\n".join(lines)


def messages_for(parsed: ParsedQuestion, cards: list[tuple[str, Edition, list]]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": render_shortlist(parsed, cards)},
    ]


def confidence_band(value: object) -> str:
    if value in CONFIDENCE:
        return str(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number > 1:
            number = number / 100.0
        if number >= 0.8:
            return "high"
        if number >= 0.55:
            return "medium"
        return "low"
    return "low"


def selection_signature(binding: Binding) -> tuple:
    items = []
    for entry in binding.selections:
        values = tuple(sorted(str(value) for value in entry["selection"]["values"]))
        items.append((entry["code"], values))
    return tuple(sorted(items))


def use_model_selections(band: str, table_id: str | None, deterministic_table: str | None, search_rank: int) -> bool:
    """High confidence keeps the model's codes. Anything else uses the deterministic plan."""
    if band != "high" or not table_id:
        return False
    if search_rank > 2 and table_id != deterministic_table:
        return False
    return True


def binding_from_model(edition: Edition, parsed: ParsedQuestion, selections: dict) -> Binding | None:
    """Build a binding from constrained codes. A published change column wins over the model's codes."""
    seeded = bind(edition, parsed)
    if seeded is not None and seeded.official_measure:
        return seeded
    if not isinstance(selections, dict):
        return None
    selected: dict[str, list[str]] = {}
    for variable in edition.variables:
        raw = selections.get(variable.code)
        if not isinstance(raw, list):
            continue
        legal = []
        allowed = set(variable.codes())
        for value in raw:
            code = str(value)
            if code in allowed and code not in legal:
                legal.append(code)
        if not legal:
            continue
        if variable.time:
            order = variable.codes()
            legal = [code for code in order if code in set(legal)]
            if parsed.operation in {"yoy_pct", "difference"} and len(legal) == 1:
                previous = _previous(order, legal[0])
                if previous and previous not in legal:
                    legal = [code for code in order if code in set(legal + [previous])]
        selected[variable.code] = legal
    if not selected:
        return None

    group_var = part_code = whole_code = None
    if parsed.operation == "share":
        for variable in edition.variables:
            codes = selected.get(variable.code)
            if variable.time or not codes:
                continue
            non_total = [code for code in codes if not is_total(variable.label(code))]
            total = next((code for code, label in variable.values if is_total(label)), None)
            if len(non_total) != 1 or total is None:
                continue
            if total not in codes:
                codes.append(total)
            group_var = variable.code
            part_code = non_total[0]
            whole_code = total
            break
        if group_var is None:
            return None

    time_var = None
    time_codes: list[str] = []
    time_variable = edition.time_variable()
    if time_variable is not None and selected.get(time_variable.code):
        time_var = time_variable.code
        time_codes = selected[time_variable.code]
    if parsed.operation in {"yoy_pct", "difference"} and len(time_codes) < 2:
        return None

    rebase_code = None
    target_code = None
    if parsed.operation == "rebase":
        if time_variable is None or parsed.rebase_year is None:
            return None
        base = _match_period(time_variable.codes(), parsed.rebase_year, None)
        if base is None:
            return None
        if base not in time_codes:
            time_codes = [code for code in time_variable.codes() if code in set(time_codes + [base])]
            selected[time_variable.code] = time_codes
        targets = [code for code in time_codes if code != base]
        if not targets:
            return None
        rebase_code = base
        target_code = targets[-1]

    px = [
        {"code": code, "selection": {"filter": "item", "values": values}}
        for code, values in selected.items()
        if values
    ]
    return Binding(
        edition=edition,
        selections=px,
        operation=parsed.operation,
        score=0,
        time_var=time_var,
        time_codes=time_codes,
        group_var=group_var,
        part_code=part_code,
        whole_code=whole_code,
        rebase_code=rebase_code,
        target_code=target_code,
        notes=["model chose the table and the value codes"],
    )


MODEL_SYSTEM = (
    _SYSTEM
    + " Use a time code the question names. "
    + "When the question does not name a subgroup, use the total row rather than a citizenship, a sex, or a region. "
    + "Immigration across the border is not migration inside the country. "
    + "A census from an earlier year does not answer a later year. "
    + "A forecast does not answer a request for the published figure. "
    + "Prefer the table whose title the question repeats. "
    + "Do not choose a table filed under earlier material when a current table is listed. "
    + "The table's years must contain the year the question asks for."
)


def _span(edition: Edition) -> str:
    years = sorted(edition.years())
    if not years:
        return ""
    if years[0] == years[-1]:
        return str(years[0])
    return f"{years[0]}-{years[-1]}"


def model_view(hits: list[Hit], parsed: ParsedQuestion, limit: int = 5, cards: list | None = None) -> str:
    """Both languages, the year span, and the candidate codes, for one shortlist."""
    lines = [f"Question: {parsed.text}", f"Arithmetic the program will apply: {parsed.operation}"]
    shown = cards if cards is not None else shortlist(hits, parsed, limit)
    for table_id, edition, variables in shown:
        sibling = None
        for hit in hits:
            if hit.table.id == table_id:
                other = hit.table.edition("is" if edition.lang == "en" else "en")
                sibling = other.title if other is not None else None
                break
        lines.append(f"\n{table_id} | {edition.title}")
        if sibling:
            lines.append(f"  other language: {sibling}")
        if edition.path_texts:
            lines.append("  path: " + " / ".join(edition.path_texts[-3:]))
        span = _span(edition)
        if span:
            lines.append(f"  years: {span}")
        for variable, values in variables:
            pairs = "; ".join(f"{code}={label}" for code, label in values)
            kind = "time" if variable.time else variable.text
            lines.append(f"  {variable.code} ({kind}): {pairs}")
    return "\n".join(lines)


def model_messages(parsed: ParsedQuestion, hits: list[Hit], error: str = "", cards: list | None = None) -> list[dict[str, str]]:
    messages = [
        {"role": "system", "content": MODEL_SYSTEM},
        {"role": "user", "content": model_view(hits, parsed, cards=cards)},
    ]
    if error:
        messages.append(
            {
                "role": "user",
                "content": "The previous query was rejected: " + error + ". Send a corrected query.",
            }
        )
    return messages


