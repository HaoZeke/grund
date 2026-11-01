"""Refusal calibrator in the style of Kamath, Jia and Liang (ACL 2020).

Five features, a logistic regression fit on dev-A plus dev2, and one
threshold. The threshold is the one that maximises the TrustSQL score at
penalty 10 while still stating at least 30% of that fit. Other sets are
reports, not another fit.

TrustSQL, penalty c = 10, on a question with a gold cell:

- a right answer scores +1
- a refusal scores 0
- a wrong answer scores -10

A question whose gold is a refusal scores +1 when refused and -10 when a
figure is stated.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

FEATURES = ("margin", "rerank", "measure", "period", "agreement")
PENALTY = 10

_MODEL: dict | None = None
_LOADED = False


def model_path() -> Path:
    override = os.environ.get("GRUND_CALIBRATOR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "calibrator.json"


def collecting() -> bool:
    return os.environ.get("GRUND_CALIBRATE", "").strip().lower() == "collect"


def _sigmoid(value: np.ndarray) -> np.ndarray:
    clipped = np.clip(value, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def fit_logistic(features: list[dict], labels: list[int], steps: int = 600, rate: float = 0.2, l2: float = 1.0) -> dict:
    """L2 logistic regression. Returns coefficients on the standardised features."""
    matrix = np.array([[float(row[name]) for name in FEATURES] for row in features], dtype=float)
    target = np.array(labels, dtype=float)
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale[scale < 1e-6] = 1.0
    scaled = (matrix - mean) / scale
    weights = np.zeros(len(FEATURES))
    bias = 0.0
    count = max(len(target), 1)
    for _ in range(steps):
        probability = _sigmoid(scaled @ weights + bias)
        residual = (probability - target) / count
        weights -= rate * (scaled.T @ residual + (l2 / count) * weights)
        bias -= rate * float(residual.sum())
    return {
        "features": list(FEATURES),
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "weights": weights.tolist(),
        "bias": bias,
        "penalty": PENALTY,
    }


def probability(features: dict, model: dict) -> float:
    mean = np.array(model["mean"], dtype=float)
    scale = np.array(model["scale"], dtype=float)
    weights = np.array(model["weights"], dtype=float)
    vector = np.array([float(features.get(name) or 0.0) for name in model["features"]], dtype=float)
    scaled = (vector - mean) / scale
    return float(_sigmoid(scaled @ weights + float(model["bias"])))


def trust_point(correct: bool, refused: bool, expect_refuse: bool = False) -> int:
    """One question under TrustSQL at penalty 10."""
    if expect_refuse:
        return 1 if refused else -PENALTY
    if refused:
        return 0
    return 1 if correct else -PENALTY


def trustsql(rows: list[dict]) -> int:
    return sum(trust_point(row["correct"], row["refused"], row.get("expect_refuse", False)) for row in rows)


def threshold_curve(rows: list[dict], model: dict) -> list[dict]:
    """TrustSQL and coverage at each cut from 0.00 to 0.99."""
    n = max(len(rows), 1)
    curve = []
    for index in range(0, 100):
        threshold = index / 100
        score = 0
        stated = 0
        for row in rows:
            if row.get("refused") or not row.get("features"):
                score += trust_point(False, True, row.get("expect_refuse", False))
                continue
            chance = probability(row["features"], model)
            if chance < threshold:
                score += trust_point(False, True, row.get("expect_refuse", False))
            else:
                stated += 1
                score += trust_point(bool(row.get("correct")), False, row.get("expect_refuse", False))
        curve.append(
            {
                "threshold": threshold,
                "trustsql": score,
                "stated": stated,
                "n": len(rows),
                "coverage": stated / n,
            }
        )
    return curve


def choose_threshold(rows: list[dict], model: dict, min_coverage: float = 0.30) -> tuple[float, int]:
    """The cut that maximises TrustSQL without refusing the whole set.

    A cut that leaves fewer than ``min_coverage`` of the rows stated is
    ineligible. Ties keep the higher cut. Already-refused rows stay refusals.
    """
    best_threshold = 0.0
    best_score = -(10**9)
    for point in threshold_curve(rows, model):
        if point["coverage"] + 1e-12 < min_coverage:
            continue
        if point["trustsql"] > best_score or (
            point["trustsql"] == best_score and point["threshold"] > best_threshold
        ):
            best_score = point["trustsql"]
            best_threshold = point["threshold"]
    return best_threshold, best_score


def save_model(model: dict, path: Path | None = None) -> None:
    target = path or model_path()
    target.write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")


def load_model() -> dict | None:
    global _MODEL, _LOADED
    if _LOADED:
        return _MODEL
    _LOADED = True
    path = model_path()
    if not path.is_file():
        _MODEL = None
        return None
    _MODEL = json.loads(path.read_text(encoding="utf-8"))
    return _MODEL


def margin_and_rerank(candidates: list | None) -> tuple[float, float]:
    scores = []
    for item in candidates or []:
        if isinstance(item, dict) and isinstance(item.get("score"), (int, float)):
            scores.append(float(item["score"]))
    scores.sort(reverse=True)
    if not scores:
        return 0.0, 0.0
    if len(scores) == 1:
        return scores[0], scores[0]
    return scores[0] - scores[1], scores[0]


def match_bits(question: str, claims: list | None) -> tuple[float, float]:
    from grund_rails.cell_claim import _measure_block, _question_period_block

    cells: list = []
    for claim in claims or []:
        cells.extend(claim.get("cells") or [])
    if not claims or not cells:
        return 0.0, 0.0
    measure = 0.0 if _measure_block(question, claims[0], cells) else 1.0
    period = 0.0 if _question_period_block(question, cells) else 1.0
    return measure, period


def agreement_score(chosen: dict, others: list[dict], index_table: str | None) -> float:
    """Share of three readers that cite the same table and, when they have one, the same value.

    A cell the retie replaced was handed to the other path. That match is not
    an independent vote.
    """
    from grund.bind2 import counts_as_path_agreement

    if not counts_as_path_agreement(chosen):
        others = []
    stem = str(chosen.get("table_id") or "").removesuffix(".px")
    value = chosen.get("value")
    votes = 0.0
    if stem and value not in (None, ""):
        votes += 1.0
    for other in others:
        other_stem = str(other.get("table_id") or "").removesuffix(".px")
        if not other_stem or other.get("value") in (None, ""):
            continue
        same_table = other_stem == stem
        try:
            same_value = abs(float(other["value"]) - float(value)) <= 1e-6 * max(1.0, abs(float(value)))
        except (TypeError, ValueError):
            same_value = False
        if same_table and same_value:
            votes += 1.0
    if index_table and str(index_table).removesuffix(".px") == stem:
        votes += 1.0
    return votes / 3.0


def feature_row(question: str, chosen: dict, others: list[dict] | None = None, index_table: str | None = None) -> dict:
    margin, rerank = margin_and_rerank(chosen.get("candidates"))
    measure, period = match_bits(question, chosen.get("claims"))
    return {
        "margin": margin,
        "rerank": rerank,
        "measure": measure,
        "period": period,
        "agreement": agreement_score(chosen, others or [], index_table),
    }


def apply_threshold(rows: list[dict], model: dict, threshold: float | None = None) -> list[dict]:
    """Copy rows with abstention applied. Already-refused rows stay refusals."""
    cut = float(model["threshold"] if threshold is None else threshold)
    applied = []
    for row in rows:
        if row.get("refused") or not row.get("features"):
            applied.append({**row, "refused": True, "abstained": False})
            continue
        chance = probability(row["features"], model)
        if chance < cut:
            applied.append({**row, "refused": True, "abstained": True, "calibrator_p": chance})
        else:
            applied.append({**row, "abstained": False, "calibrator_p": chance})
    return applied


def _expect_refuse(row: dict) -> bool:
    return bool(row.get("expect_refuse") or row.get("expect") == "refuse")


def outcome(row: dict) -> str:
    """right, wrong, or abstain. A gold refusal that is refused is right."""
    if _expect_refuse(row):
        return "right" if row.get("refused") else "wrong"
    if row.get("refused"):
        return "abstain"
    return "right" if row.get("correct") else "wrong"


def report_block(rows: list[dict]) -> dict:
    """Coverage, wrong-when-answering, and TrustSQL for one scored set.

    TrustSQL is a signed sum, not a proportion. ``error_rate`` is wrong/n,
    and its Wilson interval is the interval on that rate, not on the sum.
    """
    from grund_eval.metrics import wilson

    n = len(rows)
    kinds = [outcome(row) for row in rows]
    stated = [row for row in rows if not row.get("refused")]
    wrong = sum(1 for kind in kinds if kind == "wrong")
    right = sum(1 for kind in kinds if kind == "right")
    wrong_stated = sum(1 for row, kind in zip(rows, kinds) if kind == "wrong" and not row.get("refused"))
    cited = sum(1 for row in stated if row.get("cited_table") and row.get("cited_link"))
    coverage = wilson(len(stated), n) if n else None
    wrong_ans = wilson(wrong_stated, len(stated)) if stated else None
    error = wilson(wrong, n) if n else None
    return {
        "n": n,
        "right": right,
        "stated": len(stated),
        "wrong": wrong,
        "wrong_when_answering": {
            "wrong": wrong_stated,
            "stated": len(stated),
            "rate": (wrong_stated / len(stated)) if stated else None,
            "wilson95": list(wrong_ans) if wrong_ans else None,
        },
        "coverage": {
            "stated": len(stated),
            "n": n,
            "rate": (len(stated) / n) if n else None,
            "wilson95": list(coverage) if coverage else None,
        },
        "trustsql": trustsql(
            [
                {
                    "correct": kind == "right",
                    "refused": bool(row.get("refused")),
                    "expect_refuse": _expect_refuse(row),
                }
                for row, kind in zip(rows, kinds)
            ]
        ),
        "error_rate": {
            "wrong": wrong,
            "n": n,
            "rate": (wrong / n) if n else None,
            "wilson95": list(error) if error else None,
            "note": "Wilson is on wrong/n. TrustSQL is the signed sum, not this proportion.",
        },
        "citation": {
            "stated": len(stated),
            "stated_with_table_and_link": cited,
        },
    }


def should_abstain(features: dict | None) -> tuple[bool, float | None]:
    """The logistic cut runs only when ``GRUND_CALIBRATE=logistic``.

    Left unset, that cut stays off. A threshold of 0.9 abstained on every
    organisers' question. The abstain policy in ``abstain_rule`` is separate.
    """
    mode = os.environ.get("GRUND_CALIBRATE", "").strip().lower()
    if mode not in {"logistic", "on"}:
        return False, None
    if not features:
        return False, None
    model = load_model()
    if not model or "threshold" not in model:
        return False, None
    chance = probability(features, model)
    return chance < float(model["threshold"]), chance
