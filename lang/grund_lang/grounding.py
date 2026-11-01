"""Allow-list for the number check.

A value label such as ``01-02-04`` is fetched metadata. Its digits are not
a second statistic. The cell's magnitude is allowed as well, because the
sentence writes a negative cell and the number finder drops the sign.
A figure that is neither a fetched cell nor one of those digits is still
rejected by the existing check.
"""

from __future__ import annotations


def metadata_figures(rows: list[dict] | None) -> list[float]:
    """Numbers a reader can see in the codes and labels of fetched rows."""
    from grund.arithmetic import ArithmeticError, to_decimal
    from grund_rails.numbers import find_numbers

    figures: list[float] = []
    for row in rows or []:
        pieces: list[str] = []
        for part in row.get("key") or []:
            pieces.append(str(part))
        for label in row.get("labels") or []:
            if isinstance(label, dict):
                pieces.extend(
                    str(label.get(field) or "")
                    for field in ("label", "code", "variable", "variable_text")
                )
            else:
                pieces.append(str(label))
        blob = " ".join(piece for piece in pieces if piece)
        for language in ("en", "is"):
            figures.extend(find_numbers(blob, language))
        raw = row.get("value")
        if raw is None:
            continue
        try:
            value = float(to_decimal(str(raw)))
        except (ArithmeticError, ValueError, TypeError):
            continue
        figures.append(value)
        figures.append(abs(value))
    return figures


def extend_allowed(allowed, rows, derived=None) -> list[float]:
    """Retired. Claims declare their numbers; this returns the list unchanged."""
    return [float(value) for value in (allowed or [])]
