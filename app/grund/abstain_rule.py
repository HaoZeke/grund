"""Abstain policies compared on dev-A plus dev2.

The score is the existing calibrator probability. The weights are not
refit here. ``GRUND_ABSTAIN_RULE`` selects one:

- ``off`` states the answer the gates already accepted
- ``derived`` refuses pair, share, or change when the score is below 0.65
- ``disagree`` refuses when the paths did not fully agree

The default is set after that comparison. A level answer is left alone
by the derived rule.
"""

from __future__ import annotations

import os

OPS = frozenset({"pair", "share", "change"})
CUT = 0.65


def rule_name() -> str:
    """Default is full path agreement. ``off`` states every gated answer."""
    raw = os.environ.get("GRUND_ABSTAIN_RULE", "disagree").strip().lower()
    if raw in {"off", "0", "none"}:
        return "off"
    if raw in {"1", "derived", "on"}:
        return "derived"
    if raw in {"", "disagree", "agreement"}:
        return "disagree"
    return "off"


def _class(operation: str | None) -> str:
    op = str(operation or "").lower()
    if op in {"pair", "ratio"}:
        return "pair"
    if op in {"share", "share_percent"}:
        return "share"
    if op in {"yoy_pct", "change", "pct_change"}:
        return "change"
    return op


def score_of(result: dict) -> float | None:
    """Chance already stored on the result, or the same weights applied again."""
    stored = result.get("calibrator_p")
    if isinstance(stored, (int, float)):
        return float(stored)
    features = result.get("features")
    if not isinstance(features, dict) or not features:
        return None
    from grund.calibrate import load_model, probability

    model = load_model()
    if not model:
        return None
    return probability(features, model)


def abstain_for_low_score(result: dict) -> bool:
    """True when this stated derived answer should be refused."""
    if result.get("refused"):
        return False
    if _class(result.get("operation")) not in OPS:
        return False
    chance = score_of(result)
    if chance is None:
        return False
    return chance < CUT


def _published_equal(value, display, other) -> bool:
    """True when both figures round to the decimals the answer actually shows."""
    try:
        left = float(str(value).replace(",", "").replace(" ", ""))
        right = float(str(other).replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return False
    text = str(display if display not in (None, "") else value)
    text = text.replace(" ", "").replace("%", "")
    if text.count(",") == 1 and text.count(".") == 0:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    places = len(text.split(".", 1)[1]) if "." in text else 0
    return round(left, places) == round(right, places)


def _stem(table) -> str:
    return str(table or "").removesuffix(".px")


def _question_names_series(result: dict) -> bool:
    """A long question word is in the cited title or labels."""
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    question = str(source.get("asked") or "")
    if not question:
        return False
    from grund.agree_hyb import aligns
    from grund_index.textutil import fold, tokens

    parts: list[str] = []
    for claim in result.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            parts.append(str(cell.get("title") or ""))
            parts.extend(str(value) for value in (cell.get("labels") or {}).values())
    blob = fold(" ".join(parts))
    blob_tokens = tokens(blob)
    question_tokens = [token for token in tokens(fold(question)) if not token.isdigit()]
    named = False
    for token in question_tokens:
        # Short words match units and grades ("milljónum", "bekkurinn").
        # A series name the question actually writes is longer.
        if len(token) < 16:
            continue
        if token in blob or any(aligns(token, other) for other in blob_tokens):
            named = True
            break
    if not named:
        return False
    # A shared wrong difference stays withheld. The bypass is for one level.
    if str(result.get("operation") or "") in {
        "difference", "yoy_pct", "change", "pct_change", "share", "sum", "pair",
    }:
        return False
    asked = fold(question)
    change = bool(
        re.search(
            r"\b(by how much|by how many|rise|rose|fell|from \d{4} to|milli ar|haekk|laekk|um hve mik)\b",
            asked,
        )
    )
    if change:
        years = set(re.findall(r"(?:19|20)\d{2}", " ".join(parts)))
        if len(years) < 2:
            return False
    totals = {
        "total", "totals", "all", "alls", "allt", "allir", "allar", "oll",
        "samtals", "heild", "heildartala",
    }
    for claim in result.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            for key, value in (cell.get("labels") or {}).items():
                label = fold(str(value))
                if not label or label in totals or label.endswith(" alls") or label.endswith(" total"):
                    continue
                if any(word in fold(str(key)) for word in ("year", "ar", "month", "manudur", "quarter")):
                    continue
                label_tokens = [token for token in tokens(label) if len(token) >= 4 and token not in totals]
                if not label_tokens:
                    continue
                if any(
                    aligns(token, asked) or token in question_tokens
                    for token in label_tokens
                    for asked in question_tokens
                ):
                    continue
                return False
    return True


def _same_figure_other_table(result: dict) -> bool:
    """Two queries, one published figure, and the historical copy is not preferred.

    The language-index vote is not a third reader of that figure. A Sögulegar
    table is not kept when the other path named the same number on a current table.
    The same table on both paths is left to the agreement score: that bucket
    still contains wrong figures. The loose gates do not clear it. They leave
    wrong levels stated next to right levels, so agreement below 1 on one
    table stays a refusal.
    """
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    other = source.get("other_value") if source else None
    value = result.get("value")
    if other in (None, "") or value in (None, ""):
        return False
    if not _published_equal(value, result.get("value_display"), other):
        return False
    table = _stem(result.get("table_id"))
    other_table = _stem(source.get("other_table"))
    if not table or not other_table or table == other_table:
        return False
    if table.startswith("SOG") and not other_table.startswith("SOG"):
        # A Sögulegar copy that ends, while the current table continues,
        # is the series the question asked for. A longer Sögulegar span
        # (settlement through 2020 beside a series that ends in 1996) is not.
        if not source.get("closed_historical"):
            return False
    return True


def abstain_for_disagreement(result: dict) -> bool:
    """True when the paths did not report one published figure.

    Full agreement still passes. A second query that lands on the same
    published figure in a different table also passes. Anything else with
    agreement below 1 is withheld.
    """
    if result.get("refused"):
        return False
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    if source.get("is_origin") or source.get("is_building"):
        return False
    if source.get("total_cell") and os.environ.get("GRUND_TOTAL_CELL", "").strip() == "1":
        return False
    if source.get("lookalike_resolved"):
        from grund.keep_gate import keep_enabled

        if keep_enabled():
            return False
    if _same_figure_other_table(result):
        return False
    # GRUND_RC1 and GRUND_RC3 mark the only path whose cell matched the question.
    # The other path missed that cell, so agreement below 1 is not a second reading.
    if source.get("sole_match"):
        return False
    features = result.get("features") or {}
    try:
        agreement = float(features.get("agreement"))
    except (TypeError, ValueError):
        return False
    return agreement < 0.999


def abstain_reason(result: dict) -> str | None:
    name = rule_name()
    if name == "derived" and abstain_for_low_score(result):
        return "derived answer below 0.65"
    if name == "disagree" and abstain_for_disagreement(result):
        return "path disagreement"
    return None
