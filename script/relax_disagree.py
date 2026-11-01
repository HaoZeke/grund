"""Lossless disagreement relaxations on dev-A plus dev2.

The 60 and the 52 are reported after the choice. They do not choose it.
Question text is not printed.
"""

from __future__ import annotations

import json
from pathlib import Path

STORE = Path("data/work/eval/ruby-e5")
ORDER = ("dev-A", "dev2", "track3-52", "org60")
FIT = {"dev-A", "dev2"}


def _load(name: str) -> list[dict]:
    path = STORE / f"{name}.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _num(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _places(display, value) -> int:
    text = str(display if display not in (None, "") else value)
    text = text.replace(" ", "").replace("%", "")
    if text.count(",") == 1 and text.count(".") == 0:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    if "." not in text:
        return 0
    fraction = text.split(".", 1)[1]
    return len(fraction)


def _rounded_equal(left, right) -> bool:
    a = _num(left.get("value"))
    b = _num(right.get("value"))
    if a is None or b is None:
        return False
    places = min(_places(left.get("value_display"), left.get("value")), _places(right.get("value_display"), right.get("value")))
    return round(a, places) == round(b, places)


def _stem(table) -> str:
    return str(table or "").removesuffix(".px")


def _cell_sig(card: dict) -> tuple:
    found = []
    for cell in card.get("cells") or []:
        if not isinstance(cell, dict):
            continue
        if cell.get("coords") or cell.get("period"):
            found.append(json.dumps({"period": cell.get("period"), "coords": cell.get("coords")}, sort_keys=True, default=str))
        elif cell.get("key") not in (None, ""):
            found.append(json.dumps(cell.get("key"), sort_keys=True, default=str))
    return tuple(sorted(found))


def _cards(row: dict) -> tuple[dict, dict]:
    pair = row.get("path_pair") if isinstance(row.get("path_pair"), dict) else {}
    left = pair.get("left") if isinstance(pair.get("left"), dict) else {}
    right = pair.get("right") if isinstance(pair.get("right"), dict) else {}
    return left, right


def _same_cell(row: dict) -> bool:
    left, right = _cards(row)
    if _stem(left.get("table_id")) == "" or _stem(left.get("table_id")) != _stem(right.get("table_id")):
        return False
    left_sig = _cell_sig(left)
    right_sig = _cell_sig(right)
    if not left_sig or not right_sig or left_sig != right_sig:
        return False
    return _rounded_equal(left, right) or (_num(left.get("value")) is not None and abs(_num(left.get("value")) - _num(right.get("value"))) <= 1e-6 * max(1.0, abs(_num(left.get("value")))))


def _same_table_rounded(row: dict) -> bool:
    left, right = _cards(row)
    if not _stem(left.get("table_id")) or _stem(left.get("table_id")) != _stem(right.get("table_id")):
        return False
    return _rounded_equal(left, right)


def _other_refused(row: dict) -> bool:
    if row.get("other_refused") is True:
        return True
    _left, right = _cards(row)
    return bool(right.get("refused")) and not bool(_left.get("refused"))


def _shipped_drop(row: dict) -> bool:
    if row.get("refused"):
        return False
    try:
        return float(row.get("agreement")) < 0.999
    except (TypeError, ValueError):
        return False


def _apply(row: dict, keep) -> dict:
    """keep(row) is true when a shipped disagreement refusal should be stated."""
    stated = dict(row)
    if row.get("refused") or not _shipped_drop(row):
        return stated
    if keep(row):
        stated["policy"] = "kept"
        return stated
    stated["refused"] = True
    stated["correct"] = bool(row.get("expect_refuse"))
    stated["policy"] = "dropped"
    return stated


def _score(rows: list[dict]) -> dict:
    right = wrong = abstain = 0
    for row in rows:
        if row.get("expect_refuse"):
            if row.get("refused"):
                right += 1
            else:
                wrong += 1
            continue
        if row.get("refused"):
            abstain += 1
            continue
        if row.get("correct"):
            right += 1
        else:
            wrong += 1
    n = len(rows)
    trust = right - 10 * wrong
    return {
        "n": n,
        "right": right,
        "wrong": wrong,
        "abstain": abstain,
        "trustsql": trust,
        "mean": trust / n if n else 0.0,
    }


def _wilson(k: int, n: int) -> str:
    if n == 0:
        return "[n/a]"
    import math
    z = 1.959963984540054
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = max(0.0, centre - margin) * 100
    hi = min(1.0, centre + margin) * 100
    return f"{100 * p:.1f}% [{lo:.1f}, {hi:.1f}]"


RULES = {
    "shipped": lambda row: False,
    "same_cell": _same_cell,
    "rounded_same_table": _same_table_rounded,
    "other_refused": _other_refused,
    "cell_or_rounded": lambda row: _same_cell(row) or _same_table_rounded(row),
    "cell_or_other": lambda row: _same_cell(row) or _other_refused(row),
    "rounded_or_other": lambda row: _same_table_rounded(row) or _other_refused(row),
    "all_three": lambda row: _same_cell(row) or _same_table_rounded(row) or _other_refused(row),
}


def main() -> None:
    sets = {name: _load(name) for name in ORDER}
    print("loaded", {name: len(rows) for name, rows in sets.items()})
    # The list: shipped disagreement drops of a gated right answer.
    print("\n# Disagreement refusals whose gated path is right")
    for name in ("dev-A", "dev2"):
        rows = sets[name]
        hits = [row for row in rows if _shipped_drop(row) and row.get("correct") and not row.get("expect_refuse")]
        wrongs = [row for row in rows if _shipped_drop(row) and not row.get("correct") and not row.get("expect_refuse")]
        print(f"\n{name} rights_dropped {len(hits)} wrongs_dropped {len(wrongs)}")
        for row in hits:
            left, right = _cards(row)
            print(
                f"{row['id']}\tag={row.get('agreement')}\tvalue={row.get('value')}\t"
                f"table={_stem(row.get('table_id'))}\tother={right.get('value')}\t"
                f"other_table={_stem(right.get('table_id'))}\tother_refused={row.get('other_refused')}\t"
                f"gate={row.get('gate')}\tcell={_same_cell(row)}\trounded={_same_table_rounded(row)}\t"
                f"detail={right.get('detail') or ''}"
            )
    print("\n# Rules on dev-A plus dev2")
    for name, keep in RULES.items():
        total_right = total_wrong = total_trust = total_n = 0
        parts = []
        lossless = True
        for set_name in ("dev-A", "dev2"):
            applied = [_apply(row, keep) for row in sets[set_name]]
            block = _score(applied)
            shipped = _score([_apply(row, RULES["shipped"]) for row in sets[set_name]])
            new_wrong = block["wrong"] - shipped["wrong"]
            if new_wrong > 0:
                lossless = False
            total_right += block["right"]
            total_wrong += block["wrong"]
            total_trust += block["trustsql"]
            total_n += block["n"]
            parts.append(f"{set_name} {block['right']} right {block['wrong']} wrong trust {block['trustsql']}")
        print(
            f"{name}\tlossless={lossless}\tunion {total_right} right {total_wrong} wrong "
            f"trust {total_trust} mean {total_trust / total_n if total_n else 0:.3f}\t" + " | ".join(parts)
        )
    print("\n# Confirmation sets, not used to choose")
    for name, keep in RULES.items():
        for set_name in ("org60", "track3-52"):
            rows = sets[set_name]
            if not rows:
                continue
            block = _score([_apply(row, keep) for row in rows])
            print(
                f"{name}\t{set_name}\tright={block['right']}\twrong={block['wrong']}\t"
                f"abstain={block['abstain']}\ttrust={block['trustsql']}\tmean={block['mean']:.3f}\t"
                f"coverage {_wilson(block['right'] + block['wrong'], block['n'])}\t"
                f"error {_wilson(block['wrong'], block['n'])}"
            )


if __name__ == "__main__":
    main()
