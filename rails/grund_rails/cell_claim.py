"""A claim must match the cells it cites and the question that asked for them.

The check stays in this tree. It blocks a wrong period, a breakdown the
question did not request, a number that is not in the cells, or a change
that does not recompute from those cells. It does not invent a replacement
figure.
"""

from __future__ import annotations

import os
import re
import unicodedata

from grund_rails.rail import Rail
from grund_rails.result import Result


def fold(text: str) -> str:
    lowered = text.lower().replace("ð", "d").replace("þ", "th").replace("æ", "ae")
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))

_TOTAL = {
    "total",
    "alls",
    "samtals",
    "all",
    "allt",
    "heild",
    "heildarfjoldi",
    "oll",
    "ollu",
}
def _birth_dimension(key: str) -> bool:
    """Country of birth. A key such as ``type of births`` is the birth count."""
    if "type of birth" in key:
        return False
    if "faedingarland" in key or "country of birth" in key:
        return True
    return bool(re.search(r"\bbirth\b", key))


_BREAKDOWN = (
    ("citizen", "citizenship", "rikisfang", "rikisborg", "thjoderni"),
    ("origin", "bakgrunn", "uppruni"),
    ("municipality", "sveitarfelag"),
    ("age", "aldur"),
)


def _years(text: str) -> set[str]:
    return set(re.findall(r"(?:19|20)\d{2}", str(text or "")))


def _number(value: object) -> float | None:
    try:
        return float(str(value).replace(" ", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _same(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-6 * max(1.0, abs(right))


def _close_percent(left: float, right: float) -> bool:
    return abs(left - right) <= 0.05


def _is_total(label: str) -> bool:
    return fold(label).strip(" .:-") in _TOTAL or fold(label).startswith("total ")


def _value_named(text: str, value: str) -> bool:
    """True when the question writes the label, not merely the dimension."""
    folded = fold(value)
    if len(folded) < 4:
        return False
    if folded in text:
        return True
    words = [word for word in re.findall(r"[a-z0-9]+", folded) if len(word) >= 4]
    return bool(words) and all(word in text for word in words[:3])


def _asks_difference(question: str) -> bool:
    text = fold(question)
    return bool(re.search(r"\b(hve mikid|how much|how many|by how)\b", text))


def _norm_period(period: str) -> str:
    text = fold(period).replace(" ", "")
    if len(text) > 1 and text[0] == "a" and text[1:].isdigit():
        return text[1:]
    return text


def _active_cells(cells: list[dict]) -> list[dict]:
    live = [cell for cell in cells if cell.get("origin") == "live"]
    if live:
        return live
    return [cell for cell in cells if cell.get("origin") != "cached"]


def _periods_match(claim_period: str, cells: list[dict]) -> bool:
    raw = str(claim_period or "")
    if fold(raw) in {"", "none"}:
        return True
    if re.search(r"\b(to|til)\b", fold(raw)):
        claimed = _years(raw)
        found = set()
        for cell in cells:
            found |= _years(str(cell.get("period") or ""))
        return bool(claimed) and claimed == found
    key = _norm_period(raw)
    return any(_norm_period(str(cell.get("period") or "")) == key for cell in cells)


def _sex_cell_values(cells: list[dict]) -> tuple[float | None, float | None]:
    """Male and female cell values. The rail's men-minus-women check uses these."""
    from grund.sexdiff import sex_side

    male = female = None
    for cell in cells:
        labels = cell.get("labels") or {}
        values = labels.values() if isinstance(labels, dict) else ()
        for label in values:
            side = sex_side(str(label))
            number = _number(cell.get("value"))
            if side == "m" and male is None:
                male = number
            elif side == "f" and female is None:
                female = number
    return male, female


def _difference(cells: list[dict]) -> float | None:
    numbered = []
    for cell in cells:
        value = _number(cell.get("value"))
        years = sorted(_years(str(cell.get("period") or "")))
        if value is None or not years:
            continue
        numbered.append((years[-1], value))
    if len(numbered) < 2:
        return None
    numbered.sort()
    return numbered[-1][1] - numbered[0][1]


def _total_cell_enabled() -> bool:
    """Off unless ``GRUND_TOTAL_CELL=1``."""
    return os.environ.get("GRUND_TOTAL_CELL", "").strip() == "1"


def _time_label(key: str, value: str) -> bool:
    if fold(key) in {"ar", "year", "manudur", "month", "timabil", "quarter", "arsfjordungur", "time"}:
        return True
    return bool(re.fullmatch(r"\d{4}([mq]\d{1,2})?", fold(value).replace(" ", "")))


def _fully_totalled(cells: list[dict]) -> bool:
    """Every non-period label is Total or Alls."""
    saw = False
    for cell in cells:
        for key, value in (cell.get("labels") or {}).items():
            if _time_label(str(key), str(value)):
                continue
            saw = True
            if not _is_total(str(value)):
                return False
    return saw


def _change_question(question: str) -> bool:
    return bool(
        re.search(
            r"\b(munadi|miklu|hve mikid|how much|by how|aukning|laekk|risen|rise|fell|fall|difference|change)\b",
            fold(question),
        )
    )


def _stem_close(left: str, right: str) -> bool:
    """Inflections of one word, not a short word inside a longer compound."""
    shared = 0
    for a, b in zip(left, right):
        if a != b:
            break
        shared += 1
    if shared < 5:
        return False
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if longer.startswith(shorter) and len(longer) - len(shorter) > 2:
        return False
    return shared >= (2 / 3) * min(len(left), len(right))


_SUBJECT_SKIP = {"hversu", "islandi", "iceland", "people", "figure", "total", "arid"}


def _content_words(question: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-z0-9]+", fold(question))
        if len(word) >= 5 and word not in _SUBJECT_SKIP and not word.isdigit()
    ]


def _title_words(cells: list[dict]) -> list[str]:
    blob_parts = []
    for cell in cells:
        blob_parts.append(str(cell.get("title") or ""))
        blob_parts.append(str(cell.get("path") or ""))
    return [word for word in re.findall(r"[a-z0-9]+", fold(" ".join(blob_parts))) if len(word) >= 5]


def _label_words(cells: list[dict]) -> list[str]:
    values = []
    for cell in cells:
        values.extend(str(value) for value in (cell.get("labels") or {}).values())
    return [word for word in re.findall(r"[a-z0-9]+", fold(" ".join(values))) if len(word) >= 5]


def _subject_stem(question: str, cells: list[dict]) -> bool:
    """The question's own words are the title's words, and any extra word is on the cell."""
    titles = _title_words(cells)
    labels = _label_words(cells)
    words = _content_words(question)
    if not words or not titles:
        return False
    matched_subject = False
    for word in words:
        if any(_stem_close(word, other) for other in titles):
            matched_subject = True
            continue
        if any(_stem_close(word, other) for other in labels):
            continue
        return False
    return matched_subject


def total_cell_keeps(question: str, result: dict) -> bool:
    """A fully totalled cell on the asked subject may survive a path disagreement.

    The other path has to be silent. A second stated figure is not overridden.
    A change, or a question with no year, is left refused.
    """
    if not _total_cell_enabled():
        return False
    if _change_question(question) or not re.search(r"(?:19|20)\d{2}", question):
        return False
    cells = [
        cell
        for claim in (result.get("claims") or [])
        if isinstance(claim, dict)
        for cell in (claim.get("cells") or [])
        if isinstance(cell, dict)
    ]
    return bool(cells) and _fully_totalled(cells) and _subject_stem(question, cells)


def _share_recompute_enabled() -> bool:
    return os.environ.get("GRUND_SHARE_RECOMPUTE", "").strip() == "1"


def _share_of_total(cells: list[dict]) -> float | None:
    """Part divided by the matching total, times 100. None when the cells are not that pair."""
    if len(cells) != 2:
        return None
    left = {fold(str(key)): fold(str(value)) for key, value in (cells[0].get("labels") or {}).items()}
    right = {fold(str(key)): fold(str(value)) for key, value in (cells[1].get("labels") or {}).items()}
    diffs = []
    for key in set(left) | set(right):
        a = left.get(key, "")
        b = right.get(key, "")
        if a != b:
            diffs.append((key, a, b))
    if len(diffs) != 1:
        return None
    key, a, b = diffs[0]
    if _time_label(key, a) or _time_label(key, b):
        return None
    if _is_total(a) and not _is_total(b):
        part_cell, whole_cell = cells[1], cells[0]
    elif _is_total(b) and not _is_total(a):
        part_cell, whole_cell = cells[0], cells[1]
    else:
        return None
    part = _number(part_cell.get("value"))
    whole = _number(whole_cell.get("value"))
    if part is None or whole is None or whole == 0 or part < 0 or whole < 0 or part > whole:
        return None
    return part / whole * 100.0


def _asks_percent(question: str) -> bool:
    """A percent change, not a share ("percentage of")."""
    text = fold(question)
    if re.search(r"\b(percentage of|percent of|hlutfall af|hlutdeild af)\b", text):
        return False
    return bool(
        re.search(
            r"\b(by what percent|what percent|percentage did|um hve m\w* prosent|prosent\w*)\b",
            text,
        )
    )


def _label_pairs(labels: dict | None) -> set[tuple[str, str]]:
    pairs = set()
    for key, value in (labels or {}).items():
        pairs.add((fold(str(key)), fold(str(value))))
    return pairs


# A total on a country-of-birth or origin variable is still that split.
# A citizenship or municipality filter left on its total is not.
_SPLIT_EVEN_IF_TOTAL = ("birth", "faeding", "origin", "bakgrunn", "uppruni")


def _origin_on() -> bool:
    return os.environ.get("GRUND_IS_ORIGIN", "0").strip().lower() in {"1", "on", "true", "yes"}


def _origin_stock_labels(text: str, labels: dict | None) -> bool:
    """True when this flag's stock question cites the origin row it named."""
    if not _origin_on():
        return False
    if re.search(r"\b(immigrated|flutt\w*\s+til|flutt\w*\s+fra|emigrat|brottflutt)\b", text):
        return False
    lived = re.search(r"\b(bjuggu|bua|lived|living|live|logheimil|january|januar|were there)\b", text)
    named = re.search(r"\b(innflytj\w*|immigrants?)\b", text) or re.search(
        r"no foreign background|engan erlendan bakgrunn|kynslod", text
    )
    if not lived or not named:
        return False
    for key, value in (labels or {}).items():
        if not any(word in fold(str(key)) for word in ("origin", "bakgrunn", "uppruni", "background")):
            continue
        label = fold(str(value))
        if re.search(r"second.generation|kynslod", text):
            return "kynslod" in label or "second generation" in label
        if re.search(r"no foreign background|engan erlendan bakgrunn", text):
            return "no foreign" in label or "enginn erlend" in label
        head = label.split()
        return bool(head) and head[0] in {"immigrant", "innflytjandi"}
    return False


def _origin_or_flow_kept(text: str, key_f: str, value_f: str) -> bool:
    """The origin or migration-type value this flag asked for is not a stray split."""
    if not _origin_on():
        return False
    if any(word in key_f for word in ("origin", "bakgrunn", "uppruni", "background")):
        if re.search(r"second.generation|kynslod", text):
            return "kynslod" in value_f or "second generation" in value_f
        if re.search(r"no foreign background|engan erlendan bakgrunn", text):
            return "no foreign" in value_f or "enginn erlend" in value_f
        head = value_f.split()[0] if value_f.split() else ""
        return head in {"immigrant", "innflytjandi"}
    if any(word in key_f for word in ("flutning", "migration")):
        if re.search(r"\b(fleiri|faerri|munur|difference|haekk|laekk)\b", text) or re.search(r"\ben\s+(?:19|20)\d{2}\b", text):
            return False
        if re.search(r"netto|net immigration|net flow|umfram", text):
            return "net" in value_f or "umfram" in value_f
        if re.search(r"\b(emigrat\w*|flutt\w*\s+fra|brottflutt\w*)\b", text):
            return "emigrat" in value_f or "brottflutt" in value_f
        if re.search(r"\bimmigrated\b", text) or re.search(r"flutt\w*\s+til", text):
            blocked = ("net", "emigrat", "brott", "umfram")
            return ("immigration" in value_f or "adflutt" in value_f) and not any(word in value_f for word in blocked)
    return False


def _unrequested_breakdown(question: str, labels: dict | None) -> bool:
    text = fold(question)
    for key, value in (labels or {}).items():
        key_f = fold(str(key))
        value_f = fold(str(value))
        total = _is_total(value_f)
        if total and not any(word in key_f for word in _SPLIT_EVEN_IF_TOTAL):
            continue
        if _birth_dimension(key_f) and not any(word in text for word in ("birth", "born", "faeding", "faedd")):
            if _is_total(value_f) and _origin_stock_labels(text, labels):
                continue
            return True
        if _origin_or_flow_kept(text, key_f, value_f):
            continue
        from grund.frame import value_named_by_frame

        if value_named_by_frame(str(value)):
            continue
        for words in _BREAKDOWN:
            if words[0] == "age":
                # Labour-force rates are published for an age span, not a total.
                # A person count still cannot cite that span when age was not asked.
                if not _person_ask(question):
                    continue
                hit = re.search(r"\b(age|aldur)\b", key_f) is not None
            else:
                hit = any(word in key_f for word in words)
            if not hit:
                continue
            if any(word in text for word in words) or _value_named(text, value_f):
                # "in Iceland" names the country, not the citizenship value Iceland.
                if words[0] == "citizen" and fold(str(value)).strip() in {"iceland", "island"}:
                    if not any(word in text for word in ("citizen", "rikisfang", "rikisborg", "nationalit", "thjoderni")):
                        return True
                continue
            from grund.istown import label_counts_as_asked

            if label_counts_as_asked(question, str(value)):
                continue
            return True
    return False


def _recompute(cells: list[dict]) -> float | None:
    numbered = []
    for cell in cells:
        value = _number(cell.get("value"))
        years = sorted(_years(str(cell.get("period") or "")))
        if value is None or not years:
            continue
        numbered.append((years[-1], value))
    if len(numbered) < 2:
        return None
    numbered.sort()
    earlier = numbered[0][1]
    later = numbered[-1][1]
    if earlier == 0:
        return None
    return (later - earlier) / abs(earlier) * 100.0


def _share_result(question: str, claim: dict, cells: list[dict], claimed: float) -> str | None:
    """None when the question is not a share. ``ok`` when the percent matches.

    Anything else is a block reason. A lone count is not the percent.
    """
    try:
        from grund_lang.ratio import is_ratio_question
    except Exception:
        return None
    if not is_ratio_question(question):
        return None
    numbers = [number for number in (_number(cell.get("value")) for cell in cells) if number is not None]
    if len(numbers) < 2:
        return "recompute_mismatch"
    inputs = claim.get("inputs") or []
    part = whole = None
    if len(inputs) >= 2:
        part = _number(inputs[0])
        whole = _number(inputs[1])
    else:
        positive = sorted(number for number in numbers if number >= 0)
        if len(positive) >= 2:
            part, whole = positive[0], positive[-1]
    if part is None or whole is None or whole == 0 or part < 0 or whole < 0 or part > whole:
        return "recompute_mismatch"
    expected = part / whole * 100.0
    if any(_same(claimed, number) for number in numbers) and not _close_percent(claimed, expected):
        return "recompute_mismatch"
    if not _close_percent(claimed, expected):
        return "recompute_mismatch"
    return "ok"


def _focus_years(question: str) -> list[str]:
    """Years written in the question. One year must be the cell's year."""
    return list(dict.fromkeys(re.findall(r"(?:19|20)\d{2}", question)))


def _cell_years(cell: dict) -> list[str]:
    bits = [str(cell.get("period") or "")]
    for key, value in (cell.get("labels") or {}).items():
        if re.search(r"year|ár|ar\b|month|mán|time", fold(str(key))):
            bits.append(str(value))
    found: list[str] = []
    for bit in bits:
        found.extend(re.findall(r"(?:19|20)\d{2}", bit))
    return found


def _question_period_block(question: str, cells: list[dict]) -> str | None:
    """A lone asked year has to be the cell's year. A range may cite either end."""
    years = _focus_years(question)
    if not years:
        return None
    if len(years) == 1:
        year = years[0]
        if not any(year in _cell_years(cell) for cell in cells):
            return "unsupported_cell"
        return None
    allowed = set(years)
    for cell in cells:
        got = _cell_years(cell)
        if got and not any(year in allowed for year in got):
            return "unsupported_cell"
    return None


def covers_question(question: str, claims: list) -> bool:
    """The cited title or labels have to share a content word with the question.

    A frame's measure words count when the flag is on. The ordinary check is
    unchanged when there is no frame.

    A bare figure from an unrelated table fails this. A question with no
    long content word is not refused for overlap.
    """
    from grund_index.textutil import SYNONYMS, tokens

    blob_parts: list[str] = []
    for claim in claims or []:
        for cell in claim.get("cells") or []:
            blob_parts.append(str(cell.get("title") or ""))
            blob_parts.append(str(cell.get("path") or ""))
            blob_parts.extend(str(value) for value in (cell.get("labels") or {}).values())
    # The sex-gap claim names the formula. The two cells are the sexes the
    # question named. Overlap on a title word is not what makes it the gap.
    if any(str(claim.get("formula") or "") in {"men - women", "women - men"} for claim in claims or []):
        return True
    blob = fold(" ".join(blob_parts))
    skip = {
        "what", "which", "were", "from", "with", "that", "this", "their", "there",
        "about", "between", "across", "during", "according", "percentage", "percent",
        "hlutfall", "prosent", "figure", "figures", "total", "totals",
        "hvada", "hvort", "thad", "tetta", "eftir", "fyrir",
    }
    from grund.agree_hyb import enabled as agree_hyb
    from grund.agree_hyb import sex_headcount, stock_january

    frame = set()
    sex_words = {
        "women", "woman", "female", "females", "konur", "kona",
        "men", "males", "male", "karlar", "karl", "karlmenn",
    }
    count_of_one_sex = bool(agree_hyb() and sex_headcount(question))
    if agree_hyb():
        frame = {"iceland", "island", "islandi", "islande"}
        if stock_january(question):
            frame.update({"january", "januar"})
    from grund.frame import current_frame

    active = current_frame()
    if active is not None and active.use and active.measure:
        from grund.frame import _MEASURE_HINTS

        if any(hint in blob for hint in _MEASURE_HINTS.get(active.measure, ())):
            return True
    content = [
        token
        for token in tokens(fold(question))
        if token not in skip and token not in frame and not token.isdigit()
    ]
    words = [token for token in content if len(token) >= 6 or (count_of_one_sex and token in sex_words)]
    if not words:
        words = [token for token in content if len(token) == 5]
    if not words:
        return True
    if _total_cell_enabled() and not _change_question(question) and re.search(r"(?:19|20)\d{2}", question):
        claim_cells = [
            cell
            for claim in claims or []
            for cell in (claim.get("cells") or [])
        ]
        if _fully_totalled(claim_cells) and _subject_stem(question, claim_cells):
            return True
    extra = {
        "people": ("population", "mannfjoldi", "inhabitants"),
        "person": ("population", "mannfjoldi"),
        "born": ("births", "faeddir", "faedingar"),
        "births": ("faeddir", "faedingar"),
        "children": ("born", "faeddir", "faedingar"),
    }
    if os.environ.get("GRUND_IS_ORIGIN", "0").strip().lower() in {"1", "on", "true", "yes"}:
        extra["immigrants"] = ("immigrant", "innflytjandi")
        extra["immigrant"] = ("immigrants", "innflytjandi")
        extra["innflytjendur"] = ("innflytjandi", "immigrant")
        extra["innflytjandi"] = ("innflytjendur", "immigrant")
        extra["immigrated"] = ("immigration", "adflutningur", "adfluttir")
        extra["emigrated"] = ("emigration", "brottfluttir", "brottflutningur")
        extra["adflutningur"] = ("immigration", "adfluttir", "netto")
        if re.search(r"moved to iceland|flutt\w*\s+til|flutt\w*\s+fra|emigrat|brottflutt", fold(question)):
            if any(word in blob for word in ("migration", "emigration", "immigration", "flutning", "adflutt", "brottflutt")):
                return True
    from grund.agree_hyb import aligns

    blob_tokens = tokens(blob)
    if agree_hyb():
        asked_tokens = tokens(fold(question))
        places = [
            token
            for token in asked_tokens
            if token.startswith("hofudborg") or token.startswith("reykjav") or token.startswith("akureyr") or token == "capital"
        ]
        if places and not any(
            token in blob or any(aligns(token, other) for other in blob_tokens)
            for token in places
        ):
            return False
    population_blob = any(mark in blob for mark in ("mannfjold", "population"))
    for word in words:
        if agree_hyb() and word in sex_words and len(word) < 6 and (not count_of_one_sex or not population_blob):
            continue
        forms = {word, *SYNONYMS.get(word, ()), *extra.get(word, ())}
        if agree_hyb() and word == "karlmenn":
            forms.update(("karlar", "male", "males"))
        if any(form in blob for form in forms):
            return True
        if agree_hyb() and word.startswith("hofudborg") and any(aligns(word, other) for other in blob_tokens):
            return True
    # "August" is covered when the cell period is 2025M08.
    for word in words:
        month = _MONTH_NUM.get(word) if "_MONTH_NUM" in globals() else None
        if month is None:
            continue
        for claim in claims or []:
            for cell in claim.get("cells") or []:
                if re.search(rf"M{month:02d}", str(cell.get("period") or ""), re.I):
                    return True
    from grund.istown import question_word_in_town_cell

    if any(question_word_in_town_cell(question, word, claims) for word in words):
        return True
    return False


def question_match_claims(question: str, claims: list | None) -> bool:
    """Years, measure, no extra breakdown, and a shared content word."""
    claims = list(claims or [])
    cells: list[dict] = []
    for claim in claims:
        cells.extend(claim.get("cells") or [])
    if not claims or not cells:
        return False
    # A sex gap is the two sex cells, including a named municipality. The
    # official label is longer than the town in the question. The match is
    # the recomputed subtraction, not a shared title word.
    if str(claims[0].get("formula") or "") in {"men - women", "women - men"}:
        return check_claim(question, claims[0], cells) is None
    if _measure_block(question, claims[0], cells):
        return False
    if not covers_question(question, claims):
        return False
    if _question_period_block(question, cells):
        return False
    for cell in cells:
        if _unrequested_breakdown(question, cell.get("labels")):
            return False
    return True


def _place_stem(token: str) -> str:
    return re.sub(r"(ogi|ogur|inum|inn|ur|ar|ir|um|i)$", "", fold(token))


def _joined_names(question: str) -> list[str]:
    found: list[str] = []
    for pattern in (
        r"(?:í|i|in)\s+([A-ZÁÉÍÓÚÝÞÆÖ][\wÁÉÍÓÚÝÞÆÖáéíóúýþæö-]{2,})\s+(?:og|and)\s+([A-ZÁÉÍÓÚÝÞÆÖ][\wÁÉÍÓÚÝÞÆÖáéíóúýþæö-]{2,})",
        r"\b([A-ZÁÉÍÓÚÝÞÆÖ][\wÁÉÍÓÚÝÞÆÖáéíóúýþæö-]{3,})\s+(?:og|and)\s+([A-ZÁÉÍÓÚÝÞÆÖ][\wÁÉÍÓÚÝÞÆÖáéíóúýþæö-]{3,})",
    ):
        for left, right in re.findall(pattern, question):
            found.extend((left, right))
    seen: list[str] = []
    for name in found:
        if name not in seen:
            seen.append(name)
    return seen


def _name_in_cell(name: str, cell: dict) -> bool:
    stem = _place_stem(name)
    if len(stem) < 4:
        return False
    for label in (cell.get("labels") or {}).values():
        other = _place_stem(str(label))
        if len(other) >= 4 and (other in stem or stem in other):
            return True
    return False


def _sum_block(question: str, claim: dict, cells: list[dict]) -> str | None:
    names = _joined_names(question)
    if len(names) < 2:
        return None
    if not re.search(r"\b(samtals|together|combined|in total|hve margir|how many|bjuggu|lived)\b", fold(question)):
        return None
    missing = [name for name in names if not any(_name_in_cell(name, cell) for cell in cells)]
    if missing:
        return "unsupported_cell"
    total = 0.0
    for name in names:
        cell = next(item for item in cells if _name_in_cell(name, item))
        value = _number(cell.get("value"))
        if value is None:
            return "wrong_number"
        total += value
    claimed = _number(claim.get("value"))
    if claimed is None or not _same(claimed, total):
        return "wrong_number"
    return "ok"


# Question words name the measure being asked. "percent" is an operation
# (by what percentage), so it is not an ask word. It still marks a cell unit.
_MEASURE_ASK = (
    ("currency", ("exchange rate", "gengi", "solugengi")),
    ("gdp", ("gdp", "landsframleidsl", "gross domestic product", "thjodarframleidsl")),
    ("index", ("visitala", "index")),
    ("rate", ("rate", "hlutfall", "per capita", "a ibua", "a mann", "frjosemi", "fertility", "per woman", "a hverja")),
    ("count", ("how many", "hve marg", "fjoldi", "mannfjold", "population", "inhabitants", "lived", "live", "bua", "bjuggu", "number")),
)
_MEASURE_CELL = {
    "currency": ("exchange rate", "gengi", "solugengi"),
    "gdp": ("gdp", "landsframleidsl", "gross domestic product", "thjodarframleidsl"),
    "index": ("visitala", "index"),
    "rate": ("rate", "hlutfall", "prosent", "percent", "per capita", "a ibua", "a mann", "frjosemi", "fertility", "per woman", "a hverja"),
    "count": ("how many", "hve marg", "fjoldi", "mannfjold", "population", "inhabitants", "lived", "live", "bua", "bjuggu", "number"),
}


def _asked_kinds(question: str) -> list[str]:
    """Kinds named in the question. A longer phrase owns its letters.

    ``exchange rate`` is currency. The ``rate`` inside it is not a second kind.
    """
    text = fold(question)
    covered = [False] * len(text)
    found: list[str] = []
    for kind, words in _MEASURE_ASK:
        for word in sorted(words, key=len, reverse=True):
            start = 0
            while True:
                at = text.find(word, start)
                if at < 0:
                    break
                span = range(at, at + len(word))
                if not any(covered[index] for index in span):
                    found.append(kind)
                    for index in span:
                        covered[index] = True
                start = at + len(word)
    return [kind for kind, _words in _MEASURE_ASK if kind in found]


def infer_measure(question: str) -> str:
    """One kind when the question names one. Blank when it names several or none."""
    kinds = _asked_kinds(question)
    if len(kinds) == 1:
        return kinds[0]
    return ""


def _cell_blob(cell: dict) -> str:
    labels = cell.get("labels") or {}
    parts = [
        str(cell.get("title") or ""),
        str(cell.get("path") or ""),
        *map(str, labels.keys()),
        *map(str, labels.values()),
    ]
    return " ".join(parts)


def _kind_in(text: str, kind: str) -> bool:
    folded = fold(text)
    return any(word in folded for word in _MEASURE_CELL.get(kind, ()))


def _label_values(cell: dict) -> str:
    labels = cell.get("labels") or {}
    return " ".join(str(value) for value in labels.values())


def _rate_value(cell: dict) -> bool:
    raw = _label_values(cell)
    text = fold(raw)
    if "%" in raw:
        return True
    return any(
        word in text
        for word in ("fertility", "frjosemi", "hlutfall", "percent", "prosent", "rate", "per woman", "per capita")
    )


def _thousands_of_people(cell: dict) -> bool:
    """A population printed in thousands is not a person count."""
    text = fold(_label_values(cell))
    if any(word in text for word in ("kron", "isk")):
        return False
    return "thous" in text or "i thus" in text


def _person_ask(question: str) -> bool:
    text = fold(question)
    blocked = ["percent", "prosent", "hlutfall", "rate", "per capita", "a mann", "a ibua"]
    from grund.judgesim_fix import enabled

    if enabled():
        blocked.append("proportion")
    if any(word in text for word in blocked):
        return False
    return bool(
        re.search(
            r"\b(population|mannfjold\w*|inhabitants|people|hve marg\w*|how many people|bua|bjuggu|live|lived|lives)\b",
            text,
        )
    )


_GDP_COMPONENT = (
    "export", "utflutning", "import", "innflutning", "consumption", "neysl",
    "revenue", "tekjur", "expenditure", "utgjold", "fjarmunamyndun", "birgda",
    "saving", "sparnad", "per capita", "a mann", "percent", "hlutfall", "ratio",
    "thjodartekj",
)


def _gdp_level_ask(question: str) -> bool:
    """GDP itself, in ISK. A percent of GDP is a different measure."""
    text = fold(question)
    if not any(word in text for word in ("gdp", "landsframleidsl", "gross domestic product", "thjodarframleidsl")):
        return False
    if any(word in text for word in ("percent", "prosent", "hlutfall", "ratio", "share", "per capita", "a mann", "a ibua")):
        return False
    return True


def _gdp_line(label: str) -> bool:
    folded = fold(label)
    if "landsframleidsl" not in folded and "gross domestic product" not in folded:
        return False
    return not any(word in folded for word in _GDP_COMPONENT)


def _gdp_level(cell: dict) -> bool:
    """The GDP aggregate in ISK. An index, a volume, or a percent is not that level."""
    if _rate_value(cell) or "%" in _label_values(cell):
        return False
    labels = fold(_label_values(cell))
    if any(word in labels for word in ("visitala", "index", "volume", "magn")):
        return False
    title = fold(str(cell.get("title") or ""))
    # "GDP by industry" is a breakdown. The headline level's title does not say so.
    if " eftir " in f" {title} " or " by " in f" {title} ":
        return False
    return any(_gdp_line(str(value)) for value in (cell.get("labels") or {}).values())


def _exchange_ask(question: str) -> bool:
    text = fold(question)
    return any(word in text for word in ("exchange rate", "gengi", "solugengi"))


def _exchange_series(cell: dict) -> bool:
    """The selling rate. An accounts line that mentions exchange-rate adjustments is not the rate."""
    title = fold(str(cell.get("title") or ""))
    labels = fold(_label_values(cell))
    blob = f"{title} {labels}"
    if any(word in blob for word in ("adjustment", "leidrett", "interest", "vextir", "rekstrar")):
        return False
    if any(word in title for word in ("per capita", "a mann", "landsframleidsl", "gross domestic", "gdp", "operating account")):
        return False
    return any(word in title for word in ("selling rate", "solugengi", "exchange rate", "gengi"))


def _reykjavik_miss(question: str, cell: dict) -> bool:
    """A Reykjavík question has to cite Reykjavík, not the Iceland total or one postcode."""
    if "reykjavik" not in fold(question):
        return False
    title = fold(str(cell.get("title") or ""))
    raw_labels = [str(value) for value in (cell.get("labels") or {}).values()]
    folded = [fold(value) for value in raw_labels]
    if not re.search(r"\b\d{3}\b", question):
        for raw, label in zip(raw_labels, folded):
            if "reykjavik" in label and re.search(r"\d{3}", raw):
                return True
    blob = title + " " + " ".join(folded)
    return "reykjavik" not in blob


def _hotels_only(question: str, cell: dict) -> bool:
    """Overnight stays in Iceland are not the hotels-only series unless hotels were asked."""
    asked = fold(question)
    if not any(word in asked for word in ("overnight", "gistin", "gestakom")):
        return False
    if any(word in asked for word in ("hotel", "guesthouse", "gistiheimil")):
        return False
    title = fold(f"{cell.get('title') or ''} {cell.get('path') or ''}")
    if any(word in title for word in ("ollum", "allartegund", "all types", "all accommodation")):
        return False
    return any(word in title for word in ("hotel", "guesthouse", "gistiheimil"))


def _not_a_person_count(cell: dict) -> bool:
    text = fold(_label_values(cell))
    return any(word in text for word in ("atkv", "vote", "kosning", "visitala", "volume index"))


def _asks_nights(text: str) -> bool:
    # gistinætur folds to gistinaet. gistinóttum folds to gistinot. gisting does not.
    return any(word in text for word in ("gistinaet", "gistinot", "overnight stay", "gestakom"))


def _has_nights(text: str) -> bool:
    return any(word in text for word in ("gistinaet", "gistinot", "overnight stay", "gestakom"))


def _registered_accommodation_miss(question: str, cell: dict) -> bool:
    """Registered accommodation is the skráð gististað series, not room capacity."""
    asked = fold(question)
    if "skrad" not in asked and "registered" not in asked:
        return False
    if not any(word in asked for word in ("gisti", "overnight", "accommodation")):
        return False
    title = fold(f"{cell.get('title') or ''} {cell.get('path') or ''}")
    return "skrad" not in title and "registered" not in title


def _count_magnitude(question: str, cell: dict) -> bool:
    """A how-many count is not a money total or an average on the same variable.

    Iceland has fewer than two million people. A negative or ten-digit figure
    on a count question is the money column, not the number of families.
    """
    asked = fold(question)
    if any(word in asked for word in ("percent", "prosent", "hlutfall", "rate")):
        return False
    if re.search(r"\b(fewer|more|less|munur|difference|laekk|haekk|fjolg|faekk)\b", asked):
        return False
    if not re.search(r"\b(how many|hve marg)\b", asked):
        return False
    if not any(word in asked for word in ("famil", "fjolskyld", "people", "person", "mann", "busett", "heimil", "ibus")):
        return False
    labels = fold(_label_values(cell))
    if any(word in labels for word in ("average", "medal", "medaltal")):
        return True
    value = _number(cell.get("value"))
    if value is None:
        return False
    if value < 0:
        return True
    return abs(value) > 2_000_000


def _overnight_miss(question: str, cell: dict) -> bool:
    asked = fold(question)
    if not _asks_nights(asked):
        return False
    blob = fold(f"{cell.get('title') or ''} {_label_values(cell)}")
    # "gisting" and "gistirými" are not overnight stays. The noun has to appear.
    if not _has_nights(blob):
        return True
    return _hotels_only(question, cell)


def _two_sided_gap(question: str, cells: list[dict]) -> bool:
    """'How many more men than women' needs both counts. One of them is not the difference."""
    text = fold(question)
    if _origin_on() and re.search(r"adflutning\w*\s+umfram\s+brott", text):
        return False
    if not re.search(r"\b(fleiri|more|minus|umfram)\b", text):
        return False
    if " than " not in text and " en " not in text and "minus" not in text and "umfram" not in text:
        return False
    return len(cells) < 2


def _asks_percent_share(question: str) -> bool:
    """A share or a percent, not a percent change."""
    text = fold(question)
    if re.search(r"\b(prosentubreyting|percent change|by what percent|um hve \w* prosent)\b", text):
        return False
    return bool(
        re.search(r"\b(hlutfall|hlutdeild|percentage|percent of|what share|what proportion)\b", text)
        or re.search(r"\bhve stort hlutfall\b", text)
    )


def _percent_unit(cell: dict) -> bool:
    blob = fold(f"{cell.get('title') or ''} {_label_values(cell)}")
    return re.search(r"(%|\bpercent\w*|\bprosent\w*|\bhlutfall\w*)", blob) is not None


def _share_unit_miss(question: str, claim: dict, cells: list[dict]) -> bool:
    """A share question may not state a headcount. Recompute it, or refuse."""
    if not _asks_percent_share(question):
        return False
    op = str(claim.get("op") or claim.get("measure") or "")
    if op in {"share", "share_percent"}:
        return False
    if cells and all(_percent_unit(cell) for cell in cells):
        return False
    return True


def _question_family(question: str) -> str | None:
    """The head measure of the question, when it is one of the attractor families."""
    text = fold(question)
    if re.search(r"\b(thorsk\w*|cod|catch\w*|caught|veidd\w*|landad\w*)\b", text):
        return "catch"
    if "byggingarvisit" in text or "building cost" in text or "construction cost" in text or (
        os.environ.get("GRUND_IS_BUILDING", "0").strip().lower() in {"1", "on", "true", "yes"} and "bulding cost" in text
    ):
        return "building"
    if "launavisital" in text or "wage index" in text:
        return "wage"
    if "vinnuafl" in text or "labour force" in text:
        return "labour"
    if re.search(
        r"\b(bjuggu|bjuggum|mannfjold\w*|population|inhabitant\w*|landsmann\w*|busett\w*|resident\w*)\b",
        text,
    ):
        return "population"
    return None


def _table_family(cell: dict) -> str | None:
    title = fold(f"{cell.get('title') or ''} {cell.get('path') or ''}")
    if re.search(r"\b(thorsk\w*|cod|afli|fiskveid\w*)\b", title) or "catch" in title:
        return "fishing"
    if "bygging" in title or (
        os.environ.get("GRUND_IS_BUILDING", "0").strip().lower() in {"1", "on", "true", "yes"}
        and ("building cost" in title or "construction cost" in title)
    ):
        return "building"
    if "launavisital" in title or "wage index" in title:
        return "wage"
    if "vinnuafl" in title or "labour force" in title:
        return "labour"
    if "utflutning" in title or re.search(r"\bexports?\b", title):
        return "exports"
    if "mannfjold" in title or "population" in title:
        return "population"
    table_id = str(cell.get("table_id") or cell.get("table") or "").upper().removesuffix(".PX")
    if table_id.startswith("MAN"):
        return "population"
    return None


_FAMILY_OK = {
    "catch": frozenset({"fishing"}),
    "building": frozenset({"building"}),
    "wage": frozenset({"wage"}),
    "labour": frozenset({"labour"}),
    "population": frozenset({"population"}),
}


def _subject_mismatch(question: str, cell: dict) -> bool:
    """The catch, a building-cost index, and a wage index have to name that subject.

    A population question refuses a recognised other subject, such as the
    labour force. A table with no recognised subject is left to the other checks.
    """
    family = _question_family(question)
    if not family:
        return False
    table = _table_family(cell)
    if family in {"catch", "building", "wage", "population"}:
        return table not in _FAMILY_OK[family]
    return table is not None and table not in _FAMILY_OK[family]


def _unqualified_wage_index(question: str) -> bool:
    """A bare wage index. Real, constant-price, or mortgage series are named."""
    asked = fold(question)
    if "launavisital" not in asked and "wage index" not in asked:
        return False
    if re.search(r"\b(real|raun)\b", asked) or "fast verdlag" in asked or "constant price" in asked:
        return False
    if any(word in asked for word in ("greidslu", "jofnun", "mortgage", "adjustment")):
        return False
    return True


def _constant_price_wage(question: str, cell: dict) -> bool:
    """The nominal monthly wage index, not LAU048xx or a constant-price series."""
    if not _unqualified_wage_index(question):
        return False
    table = str(cell.get("table_id") or cell.get("table") or "").upper().removesuffix(".PX")
    if table.startswith("LAU048"):
        return True
    title = fold(str(cell.get("title") or ""))
    return any(
        word in title
        for word in ("fast verdlag", "constant price", "fostu verd", "greidslu", "jofnun", "mortgage")
    )


def _immigrant_stock(question: str, cell: dict) -> bool:
    """Origin 'Immigrant' on a population table is the stock of people of that origin.

    It is not the number who immigrated during the asked year. A migration
    table (the flow) is a different measure. A question that names origin or
    background is asking for the stock and may cite it.
    """
    from grund.frame import current_frame

    frame = current_frame()
    if frame is not None and frame.use and frame.measure == "immigrant_stock":
        return False
    asked = fold(question)
    if _origin_stock_labels(asked, cell.get("labels")):
        return False
    if not any(word in asked for word in ("immigrant", "innflytj")):
        return False
    if any(word in asked for word in ("origin", "background", "bakgrunn", "uppruni")):
        return False
    origin = ""
    for key, value in (cell.get("labels") or {}).items():
        if any(word in fold(str(key)) for word in ("origin", "bakgrunn", "uppruni")):
            origin = fold(str(value))
    if not any(word in origin for word in ("immigrant", "innflytj")):
        return False
    title = fold(str(cell.get("title") or ""))
    if any(word in title for word in ("migration", "immigration", "flutning", "adflutt")):
        return False
    return any(word in title for word in ("population", "mannfjold", "origin", "bakgrunn"))


def _immigrant_total(question: str, cell: dict) -> bool:
    """A count of immigrants is the origin row, not the total on that table.

    "Income of immigrants" is a different measure. The word only forces the
    origin row when the question asks how many people.
    """
    if not _person_ask(question):
        return False
    asked = fold(question)
    if not any(word in asked for word in ("immigrant", "innflytj")):
        return False
    blob = fold(f"{cell.get('title') or ''} {_label_values(cell)}")
    return not any(word in blob for word in ("immigrant", "innflytj"))


def _change_miss(question: str, claim: dict, cells: list[dict]) -> bool:
    """A point change needs both months. One index level is not the rise.

    Other "by how much" questions may cite the published change as one cell.
    """
    text = fold(question)
    if not re.search(r"\b(points|stig)\b", text):
        return False
    if str(claim.get("op") or "") in {"difference", "change"} and len(cells) >= 2:
        return False
    return len(cells) < 2


def _unemployment_ask(question: str) -> bool:
    text = fold(question)
    return "unemploy" in text or "atvinnuleys" in text


def _rate_unit(cell: dict) -> bool:
    text = fold(_label_values(cell))
    return any(word in text for word in ("%", "percent", "prosent", "hlutfall", "rate"))


def _weather_ask(question: str) -> bool:
    text = fold(question)
    return any(word in text for word in ("hitinn", "hiti", "temperature", "vedur", "weather", "gaer"))


def _births_from_citizenship(question: str, cell: dict) -> bool:
    """Children born are live births, not a grant of citizenship by birthplace."""
    asked = fold(question)
    if not any(word in asked for word in ("born", "faedd", "births")):
        return False
    if any(word in asked for word in ("citizenship", "rikisfang")):
        return False
    title = fold(str(cell.get("title") or ""))
    return "citizenship" in title or "rikisfang" in title


def _unnamed_capital(question: str, cell: dict) -> bool:
    """A Reykjavík table does not answer a question that named Iceland and not the city."""
    asked = fold(question)
    if "reykjavik" in asked or not any(word in asked for word in ("iceland", "island")):
        return False
    blob = fold(f"{cell.get('title') or ''} {_label_values(cell)}")
    return "reykjavik" in blob


def _mars_population(question: str, cell: dict) -> bool:
    """Mars is not a month when the question asks for its population."""
    if not _person_ask(question) or not re.search(r"\bmars\b", fold(question)):
        return False
    blob = fold(f"{cell.get('title') or ''} {_label_values(cell)}")
    return "mars" not in blob


_MONTH_NUM = {
    "january": 1, "januar": 1, "february": 2, "februar": 2, "march": 3, "mars": 3,
    "april": 4, "may": 5, "mai": 5, "june": 6, "juni": 6, "july": 7, "juli": 7,
    "august": 8, "agust": 8, "september": 9, "october": 10, "oktober": 10,
    "november": 11, "desember": 12, "december": 12,
}
_GEO_KEYS = ("sveitarfelag", "municipality", "landshluti", "landsvaedi", "region", "byggd")
_FRAME_WORDS = {
    "island", "islandi", "islands", "iceland", "landsins", "landinu", "landid",
    "thjodin", "folki", "folks", "people", "children", "born",
    "hversu", "hvort", "hvada", "hverjir", "hverjar",
    "sveitarfelag", "sveitarfelagi", "sveitarfelogum", "municipality", "utlond", "utlondum",
}
_PLACE_STEMS: set[str] | None = None


def _asked_month(question: str) -> int | None:
    """A month of a monthly series. ``1. janúar`` is a stock date, not January."""
    text = fold(question)
    if re.search(r"\b(arsmedalt\w*|annual average)\b", text):
        return None
    names = "|".join(sorted(_MONTH_NUM, key=len, reverse=True))
    stripped = re.sub(rf"\b\d{{1,2}}\s*\.?\s*(?:{names})\b", " ", text)
    stripped = re.sub(rf"\b(?:{names})\s+(?:19|20)\d{{2}}\s*=\s*100\b", " ", stripped)
    found = []
    for name, number in _MONTH_NUM.items():
        if re.search(rf"\b{name}\b", stripped):
            if name == "mars" and re.search(r"\b(population|mannfjold|people|planet)\b", text):
                continue
            found.append(number)
    if len(found) != 1:
        return None
    return found[0]


def _cell_month(cell: dict) -> int | None:
    period = str(cell.get("period") or "")
    match = re.search(r"M(\d{2})", period, re.IGNORECASE)
    if match:
        return int(match.group(1))
    blob = fold(" ".join(str(value) for value in (cell.get("labels") or {}).values()))
    for name, number in _MONTH_NUM.items():
        if re.search(rf"\b{name}\b", blob):
            return number
    return None


def _asked_quarter(question: str) -> int | None:
    text = fold(question)
    if not re.search(r"\b(quarter|arsfjordung\w*)\b", text):
        return None
    named = (
        ("first", "1st", "fyrsta", "fyrsti"),
        ("second", "2nd", "odrum", "annan", "annar"),
        ("third", "3rd", "thridja", "thridji"),
        ("fourth", "4th", "fjorda", "fjordi"),
    )
    for number, words in enumerate(named, start=1):
        if any(re.search(rf"\b{word}\b", text) for word in words):
            return number
    match = re.search(r"\b([1-4])\b", text)
    return int(match.group(1)) if match else None


def _period_unaccounted(question: str, cell: dict) -> bool:
    """A named month has to be that month on a price index. A stock date is not one."""
    if re.search(r"\b(and what|og hver|og hvad)\b", fold(question)):
        return False
    month = _asked_month(question)
    if month is not None:
        title = fold(str(cell.get("title") or ""))
        if re.search(r"\b(arsmedalt\w*|annual average)\b", title):
            return True
        got = _cell_month(cell)
        index = any(word in title or word in fold(question) for word in ("visital", "neysluverd", "consumer price"))
        if index and got != month:
            return True
        if got is not None and got != month:
            return True
    quarter = _asked_quarter(question)
    if quarter is None:
        return False
    period = str(cell.get("period") or "").upper().replace("Á", "A")
    return f"Q{quarter}" not in period and f"A{quarter}" not in period


def _place_stems() -> set[str]:
    """Municipality and region labels from the catalogue, folded once."""
    global _PLACE_STEMS
    if _PLACE_STEMS is not None:
        return _PLACE_STEMS
    found: set[str] = set()
    try:
        import gzip
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "data" / "index" / "tables.jsonl.gz"
        if not path.is_file():
            _PLACE_STEMS = found
            return found
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if row.get("lang") != "is":
                    continue
                for variable in row.get("variables") or []:
                    key = fold(str(variable.get("text") or ""))
                    if not any(word in key for word in _GEO_KEYS):
                        continue
                    for _code, label in variable.get("values") or []:
                        token = fold(str(label))
                        if len(token) < 5 or token in _FRAME_WORDS or _is_total(token):
                            continue
                        if not any(word in key for word in ("sveitarfelag", "municipality")):
                            continue
                        found.add(token)
                        for suffix in ("kaupstadur", "urborg", "baer", "borg"):
                            if token.endswith(suffix) and len(token) - len(suffix) >= 5:
                                found.add(token[: -len(suffix)])
    except Exception:
        found = set()
    _PLACE_STEMS = found
    return found


def _question_places(question: str) -> list[str]:
    stems = _place_stems()
    if not stems:
        return []
    found: list[str] = []
    for word in re.findall(r"[a-z0-9]+", fold(question)):
        if word in _FRAME_WORDS or len(word) < 5:
            continue
        forms = {word}
        if len(word) > 5 and word.endswith("i"):
            forms.add(word[:-1])
        if len(word) > 6 and word.endswith("um"):
            forms.add(word[:-2])
        for form in forms:
            if form in found:
                continue
            if form in stems or any(place.startswith(form) and len(form) >= 6 for place in stems):
                found.append(form)
    return found


def _region_unaccounted(question: str, cell: dict) -> bool:
    """A named municipality has to be the cell's label, and a region label has to be named."""
    labels = cell.get("labels") or {}
    places = _question_places(question)
    if not places:
        return False
    blob = fold(f"{cell.get('title') or ''} " + " ".join(str(value) for value in labels.values()))
    for place in places:
        if place in blob:
            return False
        # "Kópavogur" is the town inside "Kópavogsbær". "South" is not "Southwest":
        # the shared piece has to be long.
        if len(place) >= 7 and place[:7] in blob:
            return False
    from grund.frame import value_named_by_frame

    if value_named_by_frame(" ".join(str(value) for value in labels.values())):
        return False
    return True


def _content_stems(question: str) -> list[str]:
    """Measure-noun stems. Months, places, and short frame words are not stems."""
    places = set(_question_places(question))
    stems: list[str] = []
    for word in re.findall(r"[a-z0-9]+", fold(question)):
        if len(word) < 8 or word in _FRAME_WORDS or word in _MONTH_NUM or word in places:
            continue
        if re.fullmatch(r"(?:19|20)\d{2}", word):
            continue
        stem = word
        for suffix in ("innar", "unum", "anna", "inn", "num", "id", "in"):
            if stem.endswith(suffix) and len(stem) - len(suffix) >= 6:
                stem = stem[: -len(suffix)]
                break
        if stem not in stems:
            stems.append(stem)
    return stems


def _measures_unaccounted(question: str, cell: dict) -> bool:
    """Every long measure noun has to show up on the cell, via its stem."""
    blob = fold(_cell_blob(cell))
    for stem in _content_stems(question):
        if stem not in blob:
            return True
    return False


def _first_born_only(question: str, cell: dict) -> bool:
    asked = fold(question)
    if re.search(r"\b(first|frumburd\w*|frumbyrd\w*)\b", asked):
        return False
    blob = fold(_label_values(cell))
    return re.search(r"\b(first born|frumburd\w*)\b", blob) is not None


def _birth_event_missing(question: str, cell: dict) -> bool:
    """A count of births is not a count of people by country of birth.

    The measure noun (births, fæðingar, fædd) has to be its own word on the
    cell. ``fæðingarland`` is the birthplace dimension, not that noun.
    """
    asked = fold(question)
    event = bool(re.search(r"\b(births|faedingar|faeddir|faeddar|faeddust|faeddist)\b", asked))
    event = event or (
        re.search(r"\b(children|born)\b", asked) is not None
        and re.search(r"\bborn\b", asked) is not None
        and re.search(r"\b(lived|live|living|population)\b", asked) is None
    )
    if not event:
        return False
    surface = fold(_cell_blob(cell))
    surface = re.sub(r"faedingarland\w*", " ", surface)
    surface = surface.replace("country of birth", " ").replace("birthplace", " ")
    return re.search(r"\b(births|faedingar|faeddir|faeddar|faedd)\b", surface) is None


def _not_headline_series(question: str, cell: dict) -> bool:
    """An unqualified question names the headline series, not a sub-index.

    ``vísitala neysluverðs`` is the consumer price index, not the 1914
    ex-housing index or the harmonised index. ``gistinætur`` is all
    registered accommodation unless the question says hotel.
    """
    asked = fold(question)
    title = fold(str(cell.get("title") or ""))
    labels = fold(_label_values(cell))
    blob = f"{title} {labels}"
    asks_cpi = ("neysluverd" in asked or "consumer price" in asked) or (
        re.search(r"\bvisital\w*\b", asked) is not None
        and not any(word in asked for word in ("launa", "bygging", "wage", "building"))
    )
    if asks_cpi and not any(word in asked for word in ("husnaed", "samraemd", "harmon", "edli", "uppruna", "1914")):
        if any(word in blob for word in ("husnaed", "samraemd", "harmon", "edli", "uppruna", "1914")):
            return True
    if any(word in asked for word in ("gistin", "gestakom", "overnight")) and not any(
        word in asked for word in ("hotel", "gistiheimil")
    ):
        if any(word in title for word in ("hotel", "gistiheimil")) and not any(
            word in title for word in ("ollum", "allartegund", "all types")
        ):
            return True
    if any(word in asked for word in ("landsframleidsl", "gdp", "gross domestic")) and not any(
        word in asked for word in ("a mann", "per capita", "per person", "utflutning", "export")
    ):
        if any(word in title for word in ("a mann", "per capita", "per person")):
            return True
        # Current prices are the headline. Constant prices and a quarter
        # are a different series unless the question names them.
        if not any(word in asked for word in ("fostu", "constant price", "fast verd", "fixed price")):
            if any(word in title for word in ("fostu verd", "constant price", "fast verdlag")):
                return True
        if not any(word in asked for word in ("arsfjord", "quarter", "fjordung")):
            if any(word in title for word in ("arsfjord", "quarterly", "by quarter")):
                return True
        for value in (cell.get("labels") or {}).values():
            value_f = fold(str(value))
            if len(value_f) < 8 or _is_total(value_f):
                continue
            if any(word in value_f for word in ("utflutning", "export", "innflutning", "neysl", "tekjur")):
                if "landsframleidsl" not in value_f and "gross domestic" not in value_f:
                    return True
    if any(word in asked for word in ("vinnuafl", "starfandi", "i vinnu", "employed", "labour force")) and not any(
        word in asked for word in ("yfirvinn", "overtime", "skola", "kennsl", "school", "teacher")
    ):
        if any(word in title for word in ("yfirvinn", "overtime", "kennsl", "grunnskol", "school", "teacher")):
            return True
    if re.search(r"\b1\s*\.?\s*jan", asked) and not any(word in asked for word in ("gistin", "gestakom", "overnight")):
        if any(word in title for word in ("gistin", "gestakom", "overnight", "hotel")):
            return True
    if "til landsins" in asked or "to the country" in asked:
        if "innanlands" in title or "internal migration" in title:
            return True
    if _question_places(question) and not any(word in asked for word in ("innflytj", "immigrant")):
        if any(word in title for word in ("innflytj", "immigrant")):
            return True
    if any(word in asked for word in ("fluttu", "flutning", "migrat")):
        if not any(word in blob for word in ("flutning", "migrat", "adflutt", "brottflutt")):
            return True
    return False


def _alls_for_named_category(question: str, cell: dict) -> bool:
    """Alls is not a stand-in for a category the question named."""
    asked = fold(question)
    labels = cell.get("labels") or {}
    if re.search(r"\bfyrsta\s+ari\w*\b", asked):
        for key, value in labels.items():
            if re.search(r"\b(aldur|age)\b", fold(str(key))) and _is_total(fold(str(value))):
                return True
    if re.search(r"\b(erlend\w*|utlending\w*|foreign\w*)\b", asked):
        for key, value in labels.items():
            key_f = fold(str(key))
            if any(word in key_f for word in ("thjoderni", "nationalit", "citizenship")) and _is_total(fold(str(value))):
                return True
    return False


def _question_measure_conflict(question: str, cell: dict) -> bool:
    """The cited unit and kind have to be the measure the question asked for."""
    if _period_unaccounted(question, cell) or _region_unaccounted(question, cell):
        return True
    if _not_headline_series(question, cell) or _alls_for_named_category(question, cell):
        return True
    if _subject_mismatch(question, cell) or _constant_price_wage(question, cell):
        return True
    if _first_born_only(question, cell) or _birth_event_missing(question, cell):
        return True
    if _weather_ask(question) and not any(word in fold(f"{cell.get('title') or ''} {_label_values(cell)}") for word in ("hiti", "temperature", "vedur")):
        return True
    if _mars_population(question, cell):
        return True
    if _births_from_citizenship(question, cell):
        return True
    if _unnamed_capital(question, cell):
        return True
    if _unemployment_ask(question):
        blob = fold(f"{cell.get('title') or ''} {_label_values(cell)}")
        if not (_rate_unit(cell) and ("unemploy" in blob or "atvinnuleys" in blob)):
            return True
    if _person_ask(question) and (_rate_value(cell) or _thousands_of_people(cell) or _not_a_person_count(cell)):
        return True
    if _gdp_level_ask(question) and not _gdp_level(cell):
        return True
    if _exchange_ask(question) and not _exchange_series(cell):
        return True
    if _immigrant_stock(question, cell):
        return True
    if _overnight_miss(question, cell) or _registered_accommodation_miss(question, cell):
        return True
    if _count_magnitude(question, cell):
        return True
    if _immigrant_total(question, cell):
        return True
    if _debt_where_assets_named(question, cell):
        return True
    if _unemployed_beside_employed(question, cell):
        return True
    if _unnamed_recovery(question, cell):
        return True
    if _superlative_total(question, cell):
        return True
    if _unnamed_cpi_base(question, cell):
        return True
    if _unnamed_projection(question, cell):
        return True
    if _listed_age_statistics(question, cell):
        return True
    return False


def _debt_where_assets_named(question: str, cell: dict) -> bool:
    """Debt is not the assets column when the question names assets."""
    asked = fold(question)
    if not any(word in asked for word in ("asset", "eign")):
        return False
    labels = fold(_label_values(cell))
    if any(word in labels for word in ("asset", "eign")):
        return False
    return any(word in labels for word in ("debt", "skuld"))


def _unemployed_beside_employed(question: str, cell: dict) -> bool:
    """The unemployed row is not the answer when the question also names the employed."""
    labels = fold(_label_values(cell))
    if "atvinnulaus" not in labels and "unemployed" not in labels:
        return False
    asked = fold(question)
    employed = len(re.findall(r"\bstarfandi\b|\bemployed\b", asked))
    unemployed = len(re.findall(r"\batvinnulaus\w*|\bunemployed\b", asked))
    return employed > 0 and employed >= unemployed


def _unnamed_recovery(question: str, cell: dict) -> bool:
    """Reuse-and-recovery is not recycling unless the question names recovery."""
    labels = fold(_label_values(cell))
    if "recovery" not in labels and "endurnyt" not in labels:
        return False
    asked = fold(question)
    if any(word in asked for word in ("recovery", "endurnyt", "recycl", "endurunn")):
        return False
    return "reuse and recovery" in labels or ("endurnot" in labels and "endurnyt" in labels)


def _superlative_total(question: str, cell: dict) -> bool:
    """A largest-municipality question is one place, not Alls or the national total.

    Sex=Total is the whole population of that place and is not this gate.
    """
    asked = fold(question)
    if not re.search(r"\b(largest|biggest|staerst\w*|fjolmennast\w*|most populous|flest\w*)\b", asked):
        return False
    totals = {
        "total", "alls", "samtals", "all", "heild",
        "iceland", "island", "whole country", "landid", "allt landid",
    }
    for key, value in (cell.get("labels") or {}).items():
        key_f = fold(str(key))
        if not any(word in key_f for word in ("municip", "sveitarfelag", "city", "localit", "byggd", "country", "land")):
            continue
        # "country" inside "country of birth" is not the municipality list.
        if "birth" in key_f or "faeding" in key_f:
            continue
        label = fold(str(value))
        if label in totals or label.startswith("alls"):
            return True
    return False


def _listed_age_statistics(question: str, cell: dict) -> bool:
    """A title that lists mean, median, and modal age is not a request for one of them.

    Naming one statistic on its own, as ``Miðaldur`` does, keeps that cell.
    """
    asked = fold(question)
    named = []
    if "mean age" in asked or "medalaldur" in asked:
        named.append("mean")
    if "median age" in asked or "midaldur" in asked:
        named.append("median")
    if "modal age" in asked or "tidasti" in asked:
        named.append("modal")
    if len(named) < 2:
        return False
    labels = fold(_label_values(cell))
    cell_kind = None
    if "mean age" in labels:
        cell_kind = "mean"
    elif "median age" in labels or "midaldur" in labels:
        cell_kind = "median"
    elif "modal age" in labels or "tidasti" in labels:
        cell_kind = "modal"
    if cell_kind is None:
        return False
    explicit = {"mean": "medalaldur", "median": "midaldur", "modal": "tidasti"}
    if explicit[cell_kind] in asked:
        return False
    return True


def _unnamed_projection(question: str, cell: dict) -> bool:
    """A projection is not the population on a date unless the question asks for one."""
    asked = fold(question)
    if re.search(r"\b(projection|forecast|mannfjoldaspa|spa)\b", asked):
        return False
    blob = fold(f"{cell.get('title') or ''} {cell.get('path') or ''}")
    return "projection" in blob or "mannfjoldaspa" in blob or "population projections" in blob


def _unnamed_cpi_base(question: str, cell: dict) -> bool:
    """A CPI question that does not name a special base stays on the 1988 index.

    'CPI by origin, March 1997 = 100' is a different series. It is allowed
    when the question itself names that base or that breakdown.
    """
    title = fold(str(cell.get("title") or ""))
    asked = fold(question)
    if "visitala neysluverds" not in title and "consumer price index" not in title and not title.startswith("cpi"):
        return False
    special = "edli og uppruna" in title or "expenditure group" in title or "1997" in title
    if not special:
        return False
    return not any(word in asked for word in ("edli", "uppruna", "expenditure group", "1997"))


def _share_of_percent_series(question: str, claim: dict, cells: list[dict]) -> bool:
    """A table titled as a percent is already the figure. Do not divide two of its rows."""
    op = str(claim.get("op") or claim.get("operation") or claim.get("measure") or "")
    if op not in {"share", "share_percent"}:
        return False
    title = fold(" ".join(str(cell.get("title") or "") for cell in cells))
    if "percent" not in title and "hlutfall" not in title:
        return False
    values = [number for number in (_number(cell.get("value")) for cell in cells) if number is not None]
    return len(values) >= 2 and all(0 <= abs(number) <= 100 for number in values)


def _implausible_stay_rate(question: str, claim: dict) -> bool:
    """Overnight stays per person are a small rate. A six-figure quotient used the wrong denominator."""
    text = fold(question)
    if not re.search(r"per inhabitant|per person|a ibua|a hvern", text):
        return False
    if not _asks_nights(text):
        return False
    value = _number(claim.get("value"))
    return value is not None and value > 1000


def _measure_conflict(kinds: list[str], blob: str, cell: dict | None = None, question: str = "") -> bool:
    if cell is not None and _exchange_ask(question) and _exchange_series(cell):
        return False
    if cell is not None and _question_measure_conflict(question, cell):
        return True
    if cell is not None and "count" in kinds and _rate_value(cell):
        return True
    if any(_kind_in(blob, kind) for kind in kinds):
        return False
    if any(kind in {"currency", "gdp", "index"} for kind in kinds):
        return True
    cell_is_rate = any(_kind_in(blob, kind) for kind in ("rate", "index", "currency"))
    return "count" in kinds and cell_is_rate


def _compound_question(question: str) -> bool:
    """Two asks joined in one sentence. One cell is not both measures."""
    text = fold(question)
    return any(
        phrase in text
        for phrase in ("and what was", "and what were", "og hver var", "og hvad var", "og hverjar voru")
    )


def _measure_block(question: str, claim: dict, cells: list[dict]) -> str | None:
    declared = str(claim.get("measure") or "")
    if declared == "share" or (not declared and _compound_question(question)):
        kinds: list[str] = []
    elif declared:
        kinds = [declared]
    else:
        kinds = _asked_kinds(question)
    no_year = not re.search(r"(?:19|20)\d{2}", question)
    if _change_miss(question, claim, cells) or _two_sided_gap(question, cells):
        return "unsupported_cell"
    if _share_unit_miss(question, claim, cells):
        return "unsupported_cell"
    if _implausible_stay_rate(question, claim) or _share_of_percent_series(question, claim, cells):
        return "unsupported_cell"
    if "reykjavik" in fold(question) and cells and all(_reykjavik_miss(question, cell) for cell in cells):
        return "unsupported_cell"
    for cell in cells:
        if _question_measure_conflict(question, cell):
            return "unsupported_cell"
        if kinds and _measure_conflict(kinds, _cell_blob(cell), cell, question):
            return "unsupported_cell"
        if no_year and _stale_cell(question, cell):
            return "unsupported_cell"
    return None


def _stale_cell(question: str, cell: dict) -> bool:
    title = f"{cell.get('title') or ''} {cell.get('path') or ''}"
    folded = fold(title)
    asked = fold(question)
    if ("census" in folded or "manntal" in folded) and "census" not in asked and "manntal" not in asked:
        return True
    span = re.search(r"((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})", title)
    cited = _cell_years(cell)
    if span and cited and span.group(2) not in cited:
        return True
    latest = re.search(r"(?:19|20)\d{2}", str(cell.get("latest_period") or ""))
    return bool(latest and cited and latest.group(0) not in cited)


def check_claim(question: str, claim: dict, cells: list[dict]) -> str | None:
    """A block reason, or None when the claim may be stated."""
    claim = claim or {}
    cells = list(cells or [])
    formula = str(claim.get("formula") or "")
    if formula in {"men - women", "women - men"}:
        claimed_gap = _number(claim.get("value"))
        male, female = _sex_cell_values(cells)
        expected = None if male is None or female is None else (male - female if formula == "men - women" else female - male)
        if expected is None or claimed_gap is None or not _same(claimed_gap, expected):
            return "recompute_mismatch"
        return None
    period_gap = _question_period_block(question, cells)
    if period_gap:
        return period_gap
    measured = _measure_block(question, claim, cells)
    if measured:
        return measured
    summed = _sum_block(question, claim, cells)
    if summed == "ok":
        return None
    if summed:
        return summed
    if not _periods_match(str(claim.get("period") or ""), cells):
        return "wrong_period"
    cell_labels: set[tuple[str, str]] = set()
    for cell in cells:
        cell_labels |= _label_pairs(cell.get("labels"))
    claimed = _number(claim.get("value"))
    claim_labels = _label_pairs(claim.get("labels"))
    if claim_labels - cell_labels:
        return "unrequested_breakdown"
    if _unrequested_breakdown(question, claim.get("labels")):
        return "unrequested_breakdown"
    for cell in cells:
        if _unrequested_breakdown(question, cell.get("labels")):
            return "unrequested_breakdown"
    if claimed is None:
        return "undeclared_number"
    share = _share_result(question, claim, cells, claimed)
    if share == "ok":
        return None
    if share:
        return share
    if _share_recompute_enabled():
        expected_share = _share_of_total(cells)
        if expected_share is not None and _close_percent(claimed, expected_share):
            return None
    if _asks_percent(question) and len(cells) >= 2:
        expected = _recompute(cells)
        if expected is None or not _close_percent(claimed, expected):
            return "recompute_mismatch"
        return None
    if _asks_difference(question) and len(cells) >= 2:
        difference = _difference(cells)
        if difference is not None and _same(claimed, difference):
            return None
    present = [number for number in (_number(cell.get("value")) for cell in cells) if number is not None]
    if not any(_same(claimed, number) for number in present):
        return "undeclared_number"
    return None


# A computed sentence is the cells. undeclared_number then means the checker
# missed a digit, and both the ranker and the tools path keep the sentence.
# Any other block reason is a retry when the next table might be the one,
# and a refusal when it cannot.
_RETRY_REASONS = {"unsupported_cell", "wrong_number", "ungrounded_number"}


def rail_effect(reason: str | None, categories: list | None = None, *, computed: bool = False) -> str:
    """``pass``, ``retry``, or ``refuse``. Both answer paths use this."""
    names = set(categories or [])
    if reason:
        names.add(reason)
    if not names or reason is None and not categories:
        return "pass"
    if "undeclared_number" in names:
        return "pass" if computed else "refuse"
    if names & _RETRY_REASONS:
        return "retry"
    return "refuse"


def evaluate(question: str, claim: dict, cells: list[dict], claims: list | None = None) -> str | None:
    """Every claim has to match. A stale cached copy is not a cell."""
    active = _active_cells(list(cells or []))
    items = list(claims) if claims else [claim or {}]
    for item in items:
        reason = check_claim(question, item, active)
        if reason:
            return reason
    return None


def _stated_figures_match(text: str, context: dict, claim: dict, cells: list[dict]) -> bool:
    """Numbers before the citation have to be the claim, a cell, or the question.

    Table codes and the updated stamp sit in the citation and are ignored.
    """
    from grund_rails.numbers import find_numbers, matches, stated_figures

    language = str(context.get("language") or "en")
    figures = stated_figures(text, language)
    if not figures:
        return True
    allowed: list[float] = []
    for raw in (claim.get("value"), claim.get("display")):
        number = _number(raw)
        if number is not None:
            allowed.append(number)
    for cell in cells:
        number = _number(cell.get("value"))
        if number is not None:
            allowed.append(number)
        for bag in (cell.get("labels"), cell.get("coords")):
            if isinstance(bag, dict):
                for item in bag.values():
                    allowed.extend(find_numbers(str(item), language))
                    allowed.extend(find_numbers(str(item), "en"))
        allowed.extend(find_numbers(str(cell.get("period") or ""), language))
    question = str(context.get("question") or context.get("user_input") or "")
    allowed.extend(find_numbers(question, language))
    allowed.extend(find_numbers(question, "en"))
    allowed.extend(find_numbers(question, "is"))
    return all(any(matches(figure, item) for item in allowed) for figure in figures)


class CellClaimRail(Rail):
    """Block an output whose claim does not survive the cell check."""

    name = "cell_claim"
    sides = ("output",)

    def decide(self, text: str, context: dict) -> Result:
        if context.get("refused") or context.get("clarify"):
            return Result.passed(self.name)
        claim = context.get("claim")
        cells = context.get("cells")
        if not isinstance(claim, dict) or not isinstance(cells, list):
            return Result.unchecked(self.name, "no claim to check")
        reason = evaluate(
            context.get("question") or "",
            claim,
            cells,
            context.get("claims") if isinstance(context.get("claims"), list) else None,
        )
        if reason is None and text and not _stated_figures_match(text, context, claim, cells):
            reason = "ungrounded_number"
        if reason is None:
            return Result.passed(self.name)
        if rail_effect(reason, [reason], computed=bool(context.get("computed"))) == "pass":
            return Result.passed(self.name)
        return Result.blocked(self.name, reason=reason, categories=[reason])
