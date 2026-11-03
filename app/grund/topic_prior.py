"""Topic-to-table prior from the public PxWeb catalogue.

Off unless ``GRUND_TOPIC_PRIOR=1``. The prior reads the subject tree
(Íbúar, Efnahagur, Atvinnuvegir, Samfélag, Umhverfi, Sögulegar), the table
titles, and the dimension names in both languages. A headline concept
(population, a region's population, a sex count, CPI, the wage index,
unemployment, GDP, overnight stays) names the table Hagstofa files as that
concept's overview. Both the catalogue ranker and the hybrid shortlist call
``maybe_topic_prior``, so a labour-market lookalike does not stay in front
of the population table.

The prior only reorders candidates. It does not write a figure, and it does
not waive the rule that the two readings have to agree.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from grund_index.catalogue import Hit
from grund_index.model import Table
from grund_index.textutil import MONTH_NAMES, fold

_POP = ("population", "mannfjoldi", "bjuggu", "inhabitants", "ibuar", "ibuafjoldi")
_SHARE = ("percent", "percentage", "hlutfall", "prosent", "share", "hlutdeild")
_HOTEL = ("hotel", "gistiheimil", "camping", "tjald", "guesthouse")
_CONSTANT = ("constant price", "constant prices", "fostu verd", "a fostu", "fostu verdlagi")
_PER_CAPITA = ("per capita", "per person", "a mann")
# A breakdown, a census, or a mid-year stock is not the 1 January key-figures series.
_NOT_BARE_POP = (
    "census", "manntal", "country of birth", "faedingarland", "by status",
    "eftir stodu", "urban nuclei", "thettbyli", "byggdakjarn", "mid-year",
    "midyear", "arsmedaltal", "1 december", "1. desember", "municipality",
    "sveitarfelag", "citizenship", "rikisfang", "immigrant", "innflytj",
    "projection", "mannfjoldaspa",
)
_NOT_GDP = (
    "percentage of gross domestic", "percent of gross domestic",
    "share of gross domestic", "share of gdp", "percent of gdp",
    "hlutfall af landsframleidsl", "hlutdeild", "% of gdp", "of gdp",
)
_NOT_CPI = ("harmonis", "samraemd", "less housing", "an husnaed", "building cost", "byggingarkostnad")
_NOT_WAGE = ("overtime", "yfirvinn", "kennslu", "grunnskol")


def enabled() -> bool:
    """Off unless ``GRUND_TOPIC_PRIOR=1``. The default shortlist is unchanged.

    The engine's baseline pass turns it off for one request only.
    """
    from grund.request_state import current

    if current().topic_prior_off:
        return False
    return os.environ.get("GRUND_TOPIC_PRIOR", "").strip().lower() in {"1", "true", "yes"}


def baseline_paths_agreed(result: dict | None) -> bool:
    """True when both readings stated the same figure.

    A prior may reorder only when this is false. An answer the two paths
    already shared is left as it was.
    """
    if not isinstance(result, dict) or result.get("refused"):
        return False
    pair = result.get("path_pair") if isinstance(result.get("path_pair"), dict) else {}
    left = pair.get("left") if isinstance(pair.get("left"), dict) else {}
    right = pair.get("right") if isinstance(pair.get("right"), dict) else {}
    if left.get("refused") or right.get("refused"):
        return False
    return _same_reading(left.get("value"), right.get("value"))


def _same_reading(left, right) -> bool:
    if left in (None, "") or right in (None, ""):
        return False
    try:
        a = float(str(left).replace(",", "").replace(" ", ""))
        b = float(str(right).replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


def maybe_topic_prior(catalogue, question: str, hits: list[Hit]) -> list[Hit]:
    """Reorder ``hits`` when the flag is on. The same list comes back when it is off."""
    if not enabled() or not hits or catalogue is None:
        return hits
    index = _index_for(catalogue)
    return index.apply(question, hits)


@dataclass
class _Concept:
    name: str
    subject: str
    ids: tuple[str, ...]
    label: str = ""
    title_marker: str = ""


@dataclass
class _Index:
    by_stem: dict[str, Table]
    regions: list[str] = field(default_factory=list)
    municipalities: list[str] = field(default_factory=list)
    verified: dict[str, bool] = field(default_factory=dict)

    def apply(self, question: str, hits: list[Hit]) -> list[Hit]:
        concept = self._concept(question)
        # The question quotes the leader's title. That table is the one it named.
        if hits and _quotes(question, hits[0].table):
            return hits
        if concept is not None and self.verified.get(concept.name, False):
            # The leader already publishes this concept. Leave it, so a right
            # reading of a same-subject table is not replaced.
            if self._serves(hits[0].table, concept):
                return hits
            promoted = self._promote(hits, concept)
            if _ids(promoted) != _ids(hits):
                return _rescored(promoted)
        # No headline concept: leave the shortlist. A title that merely
        # contains "Iceland" is not a reason to state a figure.
        return hits

    def _concept(self, question: str) -> _Concept | None:
        text = _pad(fold(question))
        named_place = _named(text, self.municipalities) or _named(text, self.regions) or _other_place(text)
        if _is_region_population(text):
            label = _region_label(text, self.regions, self.municipalities)
            if label:
                return _Concept("region", "Ibuar", ("MAN03250",), label=label)
        # A named town or region is not the national key-figures series.
        if not named_place and _is_sex_count(text):
            return _Concept("sex", "Ibuar", ("MAN00101",), label=_sex_label(text))
        if not named_place and _is_population(text):
            return _Concept(
                "population",
                "Ibuar",
                ("MAN00101",),
                title_marker="population",
            )
        if _is_cpi(text):
            return _Concept("cpi", "Efnahagur", ("VIS01000",), title_marker="consumer price")
        if _is_wage(text):
            return _Concept("wage", "Samfelag", ("LAU04000",), title_marker="wage index")
        if _is_unemployment(text):
            return _Concept("unemployment", "Samfelag", ("VIN00910", "VIN00920"), title_marker="unemployment")
        if _is_gdp(text):
            if any(phrase in text for phrase in _CONSTANT):
                return _Concept("gdp-constant", "Efnahagur", ("THJ01103",), title_marker="landsframleidsl")
            return _Concept("gdp", "Efnahagur", ("THJ01102",), title_marker="landsframleidsl")
        if _is_overnight(text):
            return _Concept("overnight", "Atvinnuvegir", ("SAM01601",), title_marker="overnight")
        return None

    def _serves(self, table: Table, concept: _Concept) -> bool:
        stem = _stem(table.id)
        if stem in concept.ids:
            return True
        if _subject(table) != concept.subject:
            return False
        if concept.name == "population":
            # The national stock is the overview. A region or municipality
            # breakdown is a different table even when its title says population.
            return stem == "MAN00101"
        if concept.name == "region":
            # MAN10001 labels a municipality group "Capital region". That is
            # not the landshlutar table, and leaving it first keeps the
            # all-regions total in front of Höfuðborgarsvæði.
            return False
        if concept.name == "gdp":
            blob = _title_blob(table)
            # Constant-price and quarterly series are not the annual current-price total.
            if any(marker in blob for marker in ("constant", "fostu", "quarter", "arsfjord")):
                return False
            return "landsframleidsl" in blob or "domestic product" in blob
        if concept.name == "gdp-constant":
            blob = _title_blob(table)
            return any(marker in blob for marker in ("constant", "fostu"))
        if concept.name == "unemployment" and stem == "VIN00001":
            return False
        if concept.label and _publishes(table, concept.label):
            return True
        if concept.title_marker and concept.title_marker in _title_blob(table):
            return True
        if concept.name == "cpi" and ("neysluverd" in _title_blob(table) or "consumer price" in _title_blob(table)):
            return True
        if concept.name == "wage" and ("launavisital" in _title_blob(table) or "wage index" in _title_blob(table)):
            return True
        if concept.name == "overnight":
            blob = _title_blob(table)
            # A hotel or camping series is not the all-accommodation total.
            if any(word in blob for word in _HOTEL):
                return False
            return "gistinaet" in blob or "overnight" in blob
        if concept.name == "unemployment" and ("atvinnuleys" in _title_blob(table) or "unemployment" in _title_blob(table)):
            return stem != "VIN00001"
        return False

    def _promote(self, hits: list[Hit], concept: _Concept) -> list[Hit]:
        """Put a table that already publishes the concept first.

        The canonical id is inserted only when the shortlist has none. Putting
        the key-figures table ahead of the sex-and-age table states the same
        number from a table the question did not need.
        """
        serving = [hit for hit in hits if self._serves(hit.table, concept)]
        if serving:
            by_stem = {_stem(hit.table.id): hit for hit in serving}
            first = next((by_stem[stem] for stem in concept.ids if stem in by_stem), serving[0])
            return [first] + [hit for hit in hits if hit is not first]
        wanted: list[Hit] = []
        seen: set[str] = set()
        by_stem = {_stem(hit.table.id): hit for hit in hits}
        for stem in concept.ids:
            table = self.by_stem.get(stem)
            if table is None:
                continue
            wanted.append(by_stem.get(stem) or Hit(table=table, score=0.0, bm25=0.0, cosine=0.0, value_boost=0.0))
            seen.add(stem)
        rest = [hit for hit in hits if _stem(hit.table.id) not in seen]
        return wanted + rest


def _index_for(catalogue) -> _Index:
    cached = getattr(catalogue, "_topic_prior_index", None)
    if cached is not None:
        return cached
    tables = list(getattr(catalogue, "tables", []) or [])
    by_stem: dict[str, Table] = {}
    for table in tables:
        stem = _stem(table.id)
        if stem not in by_stem:
            by_stem[stem] = table
    index = _Index(by_stem=by_stem)
    index.regions = _labels(by_stem.get("MAN03250"), ("landshlut", "region"))
    index.municipalities = _labels(by_stem.get("MAN02005"), ("sveitarfelag", "municipality"))
    index.verified = {
        "region": _verified(by_stem.get("MAN03250"), ("region", "landshlut")),
        "sex": _verified(by_stem.get("MAN00101"), ("sex", "kyn")),
        "population": _verified(by_stem.get("MAN00101"), ("sex", "kyn")),
        "cpi": _verified(by_stem.get("VIS01000"), ("consumer price", "neysluverd")),
        "wage": _verified(by_stem.get("LAU04000"), ("wage index", "launavisital")),
        "unemployment": _verified(by_stem.get("VIN00910"), ("unemployment", "atvinnuleys")),
        "gdp": _verified(by_stem.get("THJ01102"), ("domestic product", "landsframleidsl"))
        and not _title_has(by_stem.get("THJ01102"), ("constant", "fostu")),
        "gdp-constant": _verified(by_stem.get("THJ01103"), ("constant", "fostu")),
        "overnight": _verified(by_stem.get("SAM01601"), ("overnight", "gistinaet")),
    }
    try:
        catalogue._topic_prior_index = index
    except Exception:
        pass
    return index


def _is_region_population(text: str) -> bool:
    return _population_cue(text) and not _labour_cue(text)


def _is_sex_count(text: str) -> bool:
    if any(phrase in text for phrase in _SHARE):
        return False
    if any(phrase in text for phrase in ("census", "manntal", "country of birth", "faedingarland")):
        return False
    return _population_cue(text) and _sex_cue(text) and not _labour_cue(text)


def _is_population(text: str) -> bool:
    if not _population_cue(text) or _sex_cue(text) or _labour_cue(text):
        return False
    if any(phrase in text for phrase in _SHARE):
        return False
    if any(phrase in text for phrase in _NOT_BARE_POP):
        return False
    return True


def _is_cpi(text: str) -> bool:
    if any(phrase in text for phrase in _NOT_CPI):
        return False
    return "consumer price" in text or "visitala neysluverd" in text or "neysluverdsvisit" in text


def _is_wage(text: str) -> bool:
    """The monthly wage index, not the family of indices and not a sector split."""
    if any(phrase in text for phrase in _NOT_WAGE):
        return False
    if "indices" in text or "visitolur" in text or "by sector" in text or "launthegahop" in text:
        return False
    if re.search(r"\bwage index\b", text):
        return True
    return re.search(r"\blaunavisital(?:a|an)\b", text) is not None


def _is_unemployment(text: str) -> bool:
    """The unemployment rate, not the word inside a quoted labour-force title."""
    if "labour force" in text or "vinnuafl" in text:
        if "unemployment rate" not in text and "atvinnuleys" not in text:
            return False
    if "unemployment rate" in text or "atvinnuleys" in text:
        return True
    return re.search(r"\bunemployment\b", text) is not None and "employed" not in text


def _is_gdp(text: str) -> bool:
    if any(phrase in text for phrase in _PER_CAPITA) or any(phrase in text for phrase in _NOT_GDP):
        return False
    return "gross domestic" in text or "landsframleidsl" in text


def _is_overnight(text: str) -> bool:
    if any(phrase in text for phrase in _HOTEL):
        return False
    return "overnight" in text or "gistinaet" in text


def _population_cue(text: str) -> bool:
    return any(word in text for word in _POP) or " lived " in text or " people " in text


def _sex_cue(text: str) -> bool:
    if " women " in text or " woman " in text or " females " in text or " female " in text:
        return True
    if " konur " in text or " konu " in text or " kvenna " in text:
        return True
    if " karlar " in text or " karla " in text or " karl " in text or " males " in text or " men " in text:
        return True
    return False


def _labour_cue(text: str) -> bool:
    return any(
        word in text
        for word in ("unemployment", "atvinnuleys", "employed", "starfandi", "labour force", "vinnuafl", "wage", "laun")
    )


_COUNTRY = {
    "island", "islandi", "islands", "islandar", "islanda", "islandur",
    "landsins", "landinu", "landid", "landi", "arid", "arinu", "januar", "januari",
}


def _other_place(text: str) -> bool:
    """A preposition names a town. The country and the calendar do not count."""
    for word in re.findall(r"\b(?:i|a)\s+([a-z0-9]+)", text):
        if word in _COUNTRY or word in MONTH_NAMES or word.isdigit() or len(word) < 4:
            continue
        return True
    return False


def _phrase_in(text: str, label: str) -> bool:
    """A catalogue label, or the same word with an Icelandic case ending."""
    if f" {label} " in text:
        return True
    if len(label) < 8:
        return False
    for word in text.split():
        if len(word) >= 6 and (word.startswith(label) or label.startswith(word)):
            return True
    return False


def _named(text: str, labels: list[str]) -> bool:
    return any(_phrase_in(text, label) for label in labels)


def region_value(edition, question: str) -> tuple[str, str] | None:
    """The published region code when the question names one.

    ``Höfuðborgarsvæðinu`` is the same label as ``Höfuðborgarsvæði``. The
    code is the one that edition prints, not a guessed one. Off with the flag.
    """
    if not enabled() or edition is None:
        return None
    text = _pad(fold(question))
    if not _is_region_population(text):
        return None
    variable = None
    for candidate in edition.variables:
        name = fold(f"{candidate.code} {candidate.text}")
        if "landshlut" in name or re.search(r"\bregion\b", name):
            variable = candidate
            break
    if variable is None:
        return None
    by_label: dict[str, str] = {}
    for code, label in variable.values:
        folded = " ".join(fold(label or "").split())
        if not folded or folded in {"total", "alls", "all", "0", "-1"}:
            continue
        by_label.setdefault(folded, str(code))
    chosen = _region_named(text, list(by_label))
    if not chosen:
        return None
    return variable.code, by_label[chosen]


def _region_named(text: str, labels: list[str]) -> str:
    """The region label itself, or that label with one case ending.

    ``capital`` is not ``capital region``. ``höfuðborgarsvæðinu`` is
    ``höfuðborgarsvæði``.
    """
    for label in sorted(labels, key=len, reverse=True):
        if len(label) >= 4 and f" {label} " in text:
            return label
    return _region_inflected(text, labels)


_MALE_LABELS = {"males", "male", "men", "man", "karlar", "karl"}
_FEMALE_LABELS = {"females", "female", "women", "woman", "konur", "kona"}


def named_cells(edition, question: str) -> list[tuple[str, str]]:
    """Region code, and the sex code when the question names one.

    A capital-region count that also says men is not the region's sex total.
    Empty unless the flag is on and a region label was named.
    """
    region = region_value(edition, question)
    if region is None:
        return []
    found = [region]
    sex = _sex_value(edition, question)
    if sex is not None:
        found.append(sex)
    return found


def _sex_value(edition, question: str) -> tuple[str, str] | None:
    """The sex row the question names, on an edition that already names a region."""
    if not enabled() or edition is None:
        return None
    text = _pad(fold(question))
    if not _sex_cue(text) or _labour_cue(text):
        return None
    wanted = _MALE_LABELS if _sex_label(text) == "males" else _FEMALE_LABELS
    for candidate in edition.variables:
        name = fold(f"{candidate.code} {candidate.text}")
        if not re.search(r"\b(kyn|sex|gender)\b", name):
            continue
        best: tuple[int, str] | None = None
        for code, label in candidate.values:
            folded = " ".join(fold(label or "").split())
            if folded not in wanted and fold(str(code)) not in wanted:
                continue
            if best is None or len(folded) < best[0]:
                best = (len(folded), str(code))
        if best is not None:
            return candidate.code, best[1]
    return None


def _same_word(word: str, part: str) -> bool:
    """Equal, or the same word with a short Icelandic ending."""
    if word == part:
        return True
    if len(part) >= 6 and word.startswith(part) and len(word) - len(part) <= 3:
        return True
    if len(word) >= 6 and part.startswith(word) and len(part) - len(word) <= 3:
        return True
    return False


def _region_inflected(text: str, labels: list[str]) -> str:
    words = [word for word in text.split() if len(word) >= 4]
    for label in sorted(labels, key=len, reverse=True):
        parts = [part for part in label.split() if len(part) >= 4]
        if parts and all(any(_same_word(word, part) for word in words) for part in parts):
            return label
    return ""


def _region_label(text: str, regions: list[str], municipalities: list[str]) -> str:
    """The region phrase the question names, when it does not name a municipality."""
    for label in municipalities:
        if len(label) >= 6 and _phrase_in(text, label):
            return ""
    for label in sorted(regions, key=len, reverse=True):
        if len(label) < 4:
            continue
        if _phrase_in(text, label):
            return label
    return ""


def _sex_label(text: str) -> str:
    if any(phrase in text for phrase in (" konur ", " konu ", " kvenna ", " women ", " woman ", " females ", " female ")):
        return "females"
    return "males"


def _labels(table: Table | None, dim_needles: tuple[str, ...]) -> list[str]:
    if table is None:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for edition in table.editions.values():
        for variable in edition.variables:
            name = fold(f"{variable.code} {variable.text}")
            if not any(needle in name for needle in dim_needles):
                continue
            for _code, label in variable.values:
                folded = " ".join(fold(label or "").split())
                if not folded or folded in {"total", "alls", "all", "0"}:
                    continue
                if folded in seen:
                    continue
                seen.add(folded)
                found.append(folded)
    return found


def _publishes(table: Table, label: str) -> bool:
    wanted = {label}
    if label == "females":
        wanted.update({"females", "female", "konur", "women", "kona"})
    if label == "males":
        wanted.update({"males", "male", "karlar", "men", "karl"})
    for edition in table.editions.values():
        for variable in edition.variables:
            for code, text in variable.values:
                if fold(text or "") in wanted or fold(code or "") in wanted:
                    return True
    return False


def _verified(table: Table | None, needles: tuple[str, ...]) -> bool:
    if table is None:
        return False
    blob = _title_blob(table) + " " + fold(" ".join(
        text for edition in table.editions.values() for text in (edition.path_texts or [])
    ))
    return any(needle in blob for needle in needles)


def _title_has(table: Table | None, needles: tuple[str, ...]) -> bool:
    if table is None:
        return False
    blob = _title_blob(table)
    return any(needle in blob for needle in needles)


def _subject(table: Table) -> str:
    for edition in table.editions.values():
        if edition.db:
            return edition.db
    return ""


def _title_blob(table: Table) -> str:
    return fold(" ".join(edition.title or "" for edition in table.editions.values()))


def _stem(table_id: str) -> str:
    base = table_id.split("#", 1)[0]
    if base.endswith(".px"):
        base = base[:-3]
    return base.upper()


def _ids(hits: list[Hit]) -> list[str]:
    return [_stem(hit.table.id) for hit in hits]


def _quotes(question: str, table: Table) -> bool:
    """True when the question pastes a run of the table's own title words."""
    blob = " ".join(fold(question).split())
    for edition in table.editions.values():
        words = [word for word in fold(edition.title or "").split() if not word.isdigit()]
        width = 5
        for start in range(0, max(0, len(words) - (width - 1))):
            phrase = " ".join(words[start : start + width])
            if len(phrase) >= 18 and phrase in blob:
                return True
    return False


def _pad(text: str) -> str:
    return f" {text} "


def _rescored(hits: list[Hit]) -> list[Hit]:
    """Scores follow the new order, so a later sort cannot restore the lookalike."""
    scored: list[Hit] = []
    for place, hit in enumerate(hits):
        scored.append(
            Hit(
                table=hit.table,
                score=5.0 - place * 0.2,
                bm25=hit.bm25,
                cosine=hit.cosine,
                value_boost=hit.value_boost,
            )
        )
    return scored
