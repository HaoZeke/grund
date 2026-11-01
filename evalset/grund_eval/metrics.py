"""Wilson score intervals for the proportions the harness reports."""

from __future__ import annotations

import math


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson interval by default. Returns None when n is 0."""
    if n <= 0:
        return None
    if successes < 0 or successes > n:
        raise ValueError("successes must be between 0 and n")
    proportion = successes / n
    z2 = z * z
    denominator = 1 + z2 / n
    centre = (proportion + z2 / (2 * n)) / denominator
    margin = z * math.sqrt(proportion * (1 - proportion) / n + z2 / (4 * n * n)) / denominator
    low = 0.0 if successes == 0 else max(0.0, centre - margin)
    high = 1.0 if successes == n else min(1.0, centre + margin)
    return (low, high)


def summarise(rows: list[dict], field: str) -> dict:
    relevant = [row for row in rows if row.get(field) is not None]
    successes = sum(1 for row in relevant if row[field])
    n = len(relevant)
    interval = wilson(successes, n) if n else None
    return {
        "n": n,
        "successes": successes,
        "accuracy": (successes / n) if n else None,
        "wilson95": list(interval) if interval else None,
    }
