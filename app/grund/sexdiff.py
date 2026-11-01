"""Men minus women on a population table.

``GRUND_SEXDIFF`` is off unless it is ``1``, ``true``, ``yes``, or ``on``.
A sex-difference question then cites the male and female cells and states
the subtraction in the question's order. "How many more women than men"
and "women minus men" are women minus men. A named municipality is that
municipality's cells on ``MAN02005``. A named place that is not one
municipality there is a refusal, not the national total. A question that
names no place stays on ``MAN00101``. The cell-claim rail recomputes the
same subtraction from the two sex labels. A time difference stays later
minus earlier.
"""

from __future__ import annotations

import os
import re

from grund.bind import Binding
from grund.parse import ParsedQuestion
from grund_index.model import Edition, Table, Variable
from grund_index.textutil import fold

_MALE = re.compile(r"\b(men|males?|karlar|karla|korlum|karl)\b")
_FEMALE = re.compile(r"\b(women|females?|konur|konu|kvenna|konum|kvenkyns)\b")
_GAP = re.compile(
    r"munadi|munar|\bmun\b|difference|differ|\bgap\b|fleiri|\bmore\b|umfram|\bminus\b|mismun"
)
_SHARE = re.compile(r"hlutfall|hlutdeild|percent|prosent|\bshare\b")
_COUNT = re.compile(
    r"fjold\w*|how many|hve marg|hversu marg|hve morg|bjuggu|bjuggum|lived|live\b|"
    r"population|mannfjold|people|inhabitants|landsmann"
)
_OTHER_MEASURE = re.compile(
    r"atvinnuleys|unemploy|launavis|wage|visital|price|verdlag|thorsk|cod\b|catch|veidd"
)
_MALE_LABEL = re.compile(r"\b(males?|men|karlar|karl)\b")
_FEMALE_LABEL = re.compile(r"\b(females?|women|konur|kona)\b")
_NOT_SEX = re.compile(r"non-binary|kynsegin|annad")
_METHOD = ("ofmat", "overestimation", "adferd", "change of method", "breytt")
_TOTAL = {"total", "alls", "samtals", "all", "allt", "heild"}
_NOT_A_PLACE = {"island", "islandi", "iceland", "islensk", "republic"}
_PLACE_SUFFIX = {
    "baer", "borg", "kaupstadur", "byggd", "hreppur", "urbyggd", "urbaer", "i", "r", "ur",
}
FORMULA_MEN = "men - women"
FORMULA_WOMEN = "women - men"
REFUSE = "refuse"
_BIN = None


def enabled() -> bool:
    return os.environ.get("GRUND_SEXDIFF", "").strip().lower() in {"1", "true", "yes", "on"}


def is_sex_difference(question: str) -> bool:
    """A count of how far the number of men and women differs.

    A share, a wage, or a count of one sex is not this question. The flag
    has to be on. Off, the caller is told this is not that family.
    """
    if not enabled():
        return False
    text = fold(question or "")
    if _SHARE.search(text) or _OTHER_MEASURE.search(text):
        return False
    if not (_MALE.search(text) and _FEMALE.search(text) and _GAP.search(text)):
        return False
    return _COUNT.search(text) is not None


def sex_side(label: str) -> str:
    """``m`` or ``f`` for a sex label, or empty."""
    text = fold(label or "")
    if _NOT_SEX.search(text):
        return ""
    male = _MALE_LABEL.search(text) is not None
    female = _FEMALE_LABEL.search(text) is not None
    if male and not female:
        return "m"
    if female and not male:
        return "f"
    return ""


def _sex_variable(edition: Edition) -> Variable | None:
    for variable in edition.variables:
        if variable.time:
            continue
        key = fold(f"{variable.code} {variable.text}")
        if "kyn" in key or "gender" in key or re.search(r"\bsex\b", key):
            return variable
    return None


def _pair(variable: Variable) -> tuple[str, str] | None:
    male = female = None
    for code, label in variable.values:
        side = sex_side(label)
        if side == "m" and male is None:
            male = code
        elif side == "f" and female is None:
            female = code
    if male is None or female is None or male == female:
        return None
    return male, female


def _total_code(variable: Variable) -> str | None:
    for code, label in variable.values:
        if fold(label) in _TOTAL:
            return code
    return None


def _population_stock(table: Table) -> bool:
    edition = table.edition("is") or table.edition("en")
    if edition is None or _sex_variable(edition) is None:
        return False
    if _pair(_sex_variable(edition) or edition.variables[0]) is None:
        return False
    blob = fold(table.titles())
    if any(word in blob for word in _METHOD):
        return False
    return "mannfjold" in blob or "population" in blob


def _geo(variable: Variable) -> bool:
    key = fold(f"{variable.code} {variable.text}")
    return "sveitarfel" in key or "municipality" in key


def _bin():
    global _BIN
    if _BIN is False:
        return None
    if _BIN is not None:
        return _BIN
    try:
        from islenska import Bin

        _BIN = Bin()
    except Exception:
        _BIN = False
        return None
    return _BIN


def _core(word: str) -> str:
    text = fold(word)
    for suffix in ("kaupstadur", "hreppur", "sveitarfelag", "baer", "borg"):
        if text.endswith(suffix) and len(text) - len(suffix) >= 4:
            return text[: -len(suffix)]
    return text


def _norm_place(text: str) -> str:
    return (
        text.replace("fjardar", "fjord")
        .replace("fjordur", "fjord")
        .replace("firdi", "fjord")
        .replace("vogs", "vog")
        .replace("vogur", "vog")
        .replace("vogi", "vog")
    )


def _same_town(name: str, label: str) -> bool:
    """The question's place name is this municipality label."""
    left = fold(name)
    if len(left) < 5 or left in _NOT_A_PLACE:
        return False
    for word in re.split(r"[\s\-]+", label or ""):
        right = _core(word)
        if len(right) < 4:
            continue
        if left == right or _norm_place(left) == _norm_place(right):
            return True
        if left.endswith("i") and left[:-1] + "ar" == right:
            return True
        if right.startswith(left) and right[len(left) :] in _PLACE_SUFFIX:
            return True
        if left.startswith(right) and left[len(right) :] in {"", "r", "i"}:
            return True
        folded = fold(word)
        if left + "r" == folded or left == folded:
            return True
    return False


def _municipalities(catalogue) -> list[tuple[str, str]]:
    table = catalogue.by_id.get("MAN02005.px")
    if table is None:
        return []
    edition = table.edition("is") or table.edition("en")
    if edition is None:
        return []
    found = []
    for variable in edition.variables:
        if not _geo(variable):
            continue
        for code, label in variable.values:
            if fold(label) in _TOTAL:
                continue
            found.append((str(code), str(label)))
    return found


def _place_names(question: str) -> tuple[list[str], list[str]]:
    """Town lemmas, and capitalized words BÍN does not know.

    A known word that is not a town, including Iceland, is neither. An
    unknown word counts as a place only when it matches one municipality.
    """
    database = _bin()
    towns: list[str] = []
    unknown: list[str] = []
    for word in re.findall(r"[A-Za-zÁÉÍÓÚÝÞÆÖÐáéíóúýþæöð]+", question or ""):
        if len(word) < 4 or not word[:1].isupper():
            continue
        if fold(word) in _NOT_A_PLACE:
            continue
        rows = []
        if database is not None:
            try:
                rows = database.lookup(word)[1]
            except Exception:
                rows = []
        found = []
        for row in rows:
            # BÍN writes a town as "þor" and a town that is also a place-name
            # as "þor,örn". Vestmannaeyjar is the second. A bare "örn" is not a town.
            parts = {piece.strip() for piece in str(getattr(row, "hluti", "")).split(",")}
            if "þor" not in parts:
                continue
            lemma = str(row.ord)
            if fold(lemma) in _NOT_A_PLACE or lemma in found:
                continue
            found.append(lemma)
        if found:
            for town in found:
                if town not in towns:
                    towns.append(town)
            continue
        if rows:
            continue
        if word not in unknown:
            unknown.append(word)
    return towns, unknown


def _codes_for(names: list[str], municipalities: list[tuple[str, str]]) -> str | None:
    chosen: set[str] = set()
    for name in names:
        hits = [code for code, label in municipalities if _same_town(name, label)]
        if len(hits) > 1:
            return REFUSE
        if len(hits) == 1:
            chosen.add(hits[0])
    if len(chosen) == 1:
        return next(iter(chosen))
    if len(chosen) > 1:
        return REFUSE
    return None


def place_code(catalogue, question: str) -> str | None:
    """The MAN02005 code for the one named municipality.

    ``None`` means the question names no place, so the national table is
    the right one. ``REFUSE`` means it names a place that is not exactly
    one municipality on that table.
    """
    towns, unknown = _place_names(question)
    municipalities = _municipalities(catalogue)
    if towns:
        return _codes_for(towns, municipalities) or REFUSE
    matched = _codes_for(unknown, municipalities)
    return matched


def _national_table(catalogue) -> Table | None:
    table = catalogue.by_id.get("MAN00101.px")
    if table is not None and _population_stock(table):
        return table
    return None


def operand_order(question: str) -> tuple[str, str]:
    """Which sex is subtracted from which.

    "X minus Y" is X minus Y. "More X than Y" and "fleiri X en Y" are X
    minus Y. "Fjölda karla og kvenna" is the first sex named minus the
    second. A frá/til change is not this function's job.
    """
    text = fold(question or "")

    def side(span: str) -> str:
        male = _MALE.search(span) is not None
        female = _FEMALE.search(span) is not None
        if male and not female:
            return "m"
        if female and not male:
            return "f"
        return ""

    minus = re.search(r"(?P<left>.{0,80}?)\bminus\b(?P<right>.{0,80})", text)
    if minus:
        left, right = side(minus.group("left")), side(minus.group("right"))
        if left and right and left != right:
            return left, right
    match = re.search(
        r"\b(?:how many more|how much more|hve marg\w* fleiri|hve morg\w* fleiri|fleiri|faerri|fewer|more|mismunur)\b"
        r"(?P<left>.{0,160}?)\b(?:than|en)\b(?P<right>.{0,160})",
        text,
    )
    if match:
        left, right = side(match.group("left")), side(match.group("right"))
        if left and right and left != right:
            return left, right
    male_at = _MALE.search(text)
    female_at = _FEMALE.search(text)
    if male_at and female_at and female_at.start() < male_at.start():
        return "f", "m"
    return "m", "f"


def formula_for(question: str) -> str:
    minuend, _subtrahend = operand_order(question)
    return FORMULA_MEN if minuend == "m" else FORMULA_WOMEN


def binding_for(catalogue, parsed: ParsedQuestion, question: str, hits: list) -> tuple[Binding, Table] | None:
    """Sex cells on MAN00101, or on MAN02005 when the question names a municipality."""
    del hits
    if not is_sex_difference(question):
        return None
    if not parsed.periods:
        return None
    year = parsed.periods[0][0]
    named = place_code(catalogue, question)
    if named == REFUSE:
        return None
    if named is None:
        table = _national_table(catalogue)
    else:
        table = catalogue.by_id.get("MAN02005.px")
        if table is None or not _population_stock(table):
            return None
    if table is None:
        return None
    edition = table.edition(parsed.language) or table.edition("en") or table.edition("is")
    if edition is None:
        return None
    sex = _sex_variable(edition)
    time_var = edition.time_variable()
    if sex is None or time_var is None:
        return None
    pair = _pair(sex)
    if pair is None:
        return None
    male, female = pair
    minuend, subtrahend = operand_order(question)
    codes = {"m": male, "f": female}
    part_code, whole_code = codes[minuend], codes[subtrahend]
    year_code = str(year) if str(year) in set(time_var.codes()) else None
    if year_code is None:
        return None
    selections = []
    placed = False
    for variable in edition.variables:
        if variable.time or variable.code == sex.code:
            continue
        if named is not None and _geo(variable):
            selections.append({"code": variable.code, "selection": {"filter": "item", "values": [named]}})
            placed = True
            continue
        total = _total_code(variable)
        if total is None:
            return None
        selections.append({"code": variable.code, "selection": {"filter": "item", "values": [total]}})
    if named is not None and not placed:
        return None
    selections.append({"code": sex.code, "selection": {"filter": "item", "values": [male, female]}})
    selections.append({"code": time_var.code, "selection": {"filter": "item", "values": [year_code]}})
    binding = Binding(
        edition=edition,
        selections=selections,
        operation="difference",
        score=1.0,
        time_var=time_var.code,
        time_codes=[year_code],
        group_var=sex.code,
        part_code=part_code,
        whole_code=whole_code,
        notes=[formula_for(question)],
    )
    return binding, table
