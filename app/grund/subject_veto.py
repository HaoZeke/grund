"""Refuse a table that drops subject words the search leader still has.

The leader is the first table after retrieval. A later table may still be
the one that binds. When the leader's title contains two or more question
words that the bound table's title does not, the bound table is a different
subject and the answer is withheld.

On unless ``GRUND_SUBJECT=0``. A stated zero on a level or a pair is withheld
unless the sentence is a percent, an index, or a rate.
"""

from __future__ import annotations

import os

from grund_index.textutil import tokens

_STOP = {
    "what", "was", "were", "hver", "hvad", "arid", "from", "fra", "til",
    "and", "the", "did", "how", "much", "many", "percentage", "percent",
    "prosent", "with", "med", "eftir", "that", "this", "sem",
}


def enabled() -> bool:
    """On unless ``GRUND_SUBJECT=0``. The held-out check used this default."""
    return os.environ.get("GRUND_SUBJECT", "1").strip().lower() not in {"0", "off", "none"}


def _content(text: str) -> set[str]:
    return {token for token in tokens(text) if len(token) >= 6 and token not in _STOP and not token.isdigit()}


def leader_title(catalogue, question: str, language: str | None, years: list[int] | None) -> str:
    """Title of the first table after the same retrieval the ranker uses."""
    from grund.headline import prefer_headline
    from grund.rerank import maybe_rerank, search_k

    found = catalogue.search(question, k=search_k(), years=years or None)
    found = maybe_rerank(catalogue, question, found, years or None)
    hits = prefer_headline(found, question)
    from grund.topic_prior import maybe_topic_prior

    hits = maybe_topic_prior(catalogue, question, hits)
    if not hits:
        return ""
    edition = hits[0].table.edition(language or "") or hits[0].table.edition("en")
    return edition.title if edition else ""


def search_leader_title(catalogue, question: str, language: str | None, years: list[int] | None) -> str:
    if not enabled():
        return ""
    return leader_title(catalogue, question, language, years)


def titles_gap(question: str, leader: str, chosen_title: str) -> bool:
    """True when the chosen title is missing two question words the leader has.

    ``chosen_title`` may be several table titles joined together. A two-part
    answer is kept when the two titles together still carry those words.
    """
    if not question or not leader or not chosen_title:
        return False
    if leader == chosen_title:
        return False
    covered = _content(question) & _content(leader)
    missing = covered - _content(chosen_title)
    return len(missing) >= 2


def subject_gap(question: str, leader: str, chosen_title: str) -> bool:
    if not enabled():
        return False
    return titles_gap(question, leader, chosen_title)


def zero_count_reason(result: dict) -> str | None:
    """A stated 0 on a count is withheld. A percent, an index, or a change may be 0."""
    if result.get("refused"):
        return None
    operation = str(result.get("operation") or "").lower()
    if operation in {"yoy_pct", "change", "pct_change", "share", "rebase", "per_capita"}:
        return None
    try:
        value = float(str(result.get("value")).replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return None
    if value != 0.0:
        return None
    from grund_index.textutil import fold

    blob = fold(str(result.get("answer") or ""))
    claims = result.get("claims") or []
    blob = fold(blob + " " + str(claims))
    if any(word in blob for word in ("percent", "hlutfall", "prosent", "index", "visitala", "rate")):
        return None
    return "zero count"
