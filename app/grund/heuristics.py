"""Selection rules already in the tree.

Every name stays on unless `GRUND_HEURISTICS_OFF` lists it. Ablation turns
one name off and rescores. A rule whose dev-A figures do not move, with
CellClaimRail on, is safe to delete.
"""

from __future__ import annotations

import os

NAMES = (
    "price_base_year",
    "after_title",
    "title_names",
    "threshold_age",
    "range_number",
    "qualified_name",
    "title_prefix",
    "share_only_when_asked",
    "count_and_share_is_level",
    "per_person_is_level",
    "points_are_difference",
    "magnitude_is_difference",
    "percent_is_change",
    "export_subtotal",
    "place_not_subgroup",
    "komum_inflection",
    "empty_latest_period",
)


# Row pickers that were fit on dev. They stay off. A fresh question that
# looks like the judge set should refuse rather than take the dev row.
_OFF_BY_DEFAULT = {
    "after_title",
    "title_names",
    "threshold_age",
    "range_number",
    "qualified_name",
    "title_prefix",
    "export_subtotal",
    "place_not_subgroup",
}


def enabled(name: str) -> bool:
    """True when this rule should run.

    `GRUND_HEURISTICS_OFF` disables names. `GRUND_CELL_RULES`, when set, is
    an allow-list used by unit tests. The dev row pickers are off unless named.
    """
    if name not in NAMES:
        return False
    off = {part.strip() for part in os.environ.get("GRUND_HEURISTICS_OFF", "").split(",") if part.strip()}
    if name in off or "all" in off:
        return False
    allow = os.environ.get("GRUND_CELL_RULES")
    if allow is not None:
        return name in {part.strip() for part in allow.split(",") if part.strip()}
    return name not in _OFF_BY_DEFAULT
