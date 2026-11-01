"""Template sentences. Every figure is passed in; nothing is calculated here."""

from __future__ import annotations

import re

from grund.arithmetic import format_stat
from grund.bind import Binding
from grund_index.model import Edition

_MONTHS = {
    "en": ["", "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
    "is": ["", "janúar", "febrúar", "mars", "apríl", "maí", "júní",
           "júlí", "ágúst", "september", "október", "nóvember", "desember"],
}


def human_period(code: str, label: str, language: str) -> str:
    monthly = re.fullmatch(r"(\d{4})M(\d{2})", code or "", re.IGNORECASE)
    if monthly:
        month = int(monthly.group(2))
        if 1 <= month <= 12:
            name = _MONTHS[language][month]
            return f"{name} {monthly.group(1)}"
    if re.fullmatch(r"\d{4}", code or ""):
        if language == "is":
            return f"árið {code}"
        return code
    if label and label.strip() and fold_label(label) != fold_label(code):
        return label.strip()
    return (label or code or "").strip()


def fold_label(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _strip_years(text: str) -> str:
    """Drop years, index bases, and other title figures so the sentence does not invent them.

    "Live expectancy for 30 years old" would otherwise put 30 next to the
    statistic, and the number check would refuse the answer.
    """
    cleaned = re.sub(r"\b1[7-9]\d{2}\s*=\s*100\b", "", text)
    cleaned = re.sub(r"=\s*100\b", "", cleaned)
    cleaned = re.sub(r"\b1[7-9]\d{2}\b|\b20\d{2}\b", "", cleaned)
    cleaned = re.sub(r"\d+(?:[.,]\d+)?", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–,=()")
    return cleaned


def measure_phrase(binding: Binding, edition: Edition, language: str) -> str:
    labels = []
    for entry in binding.selections:
        variable = edition.variable(entry["code"])
        if variable is None or variable.time:
            continue
        if binding.group_var and entry["code"] == binding.group_var:
            code = binding.part_code
            if code:
                labels.append(variable.label(code))
            continue
        for code in entry["selection"]["values"][:2]:
            label = variable.label(code)
            if label and label.lower() not in {"total", "samtals"}:
                labels.append(label)
    topic = _strip_years(edition.title)
    if labels:
        joined = ", ".join(dict.fromkeys(labels))
        if language == "is":
            return f"{joined} í {topic}" if topic else joined
        return f"{joined} in {topic}" if topic else joined
    return topic or edition.title


def render(
    language: str,
    edition: Edition,
    binding: Binding,
    rows: list[dict],
    primary_raw: str,
    derived: dict | None,
    preliminary: bool,
) -> str:
    display = format_stat(primary_raw, language)
    if derived and derived["name"] in {"yoy_pct", "share_percent"}:
        display = display + (" prósent" if language == "is" else " percent")
    period = _period_phrase(binding, edition, rows, language)
    measure = measure_phrase(binding, edition, language)
    if language == "is":
        when = period if period.startswith("árið") else f"Í {period}"
        sentence = f"{when} var {measure} {display}."
    else:
        sentence = f"In {period}, {measure} was {display}."
    if derived and derived["name"] == "yoy_pct" and len(rows) >= 2:
        earlier = format_stat(rows[0]["value"], language)
        later = format_stat(rows[-1]["value"], language)
        earlier_when = human_period(rows[0]["map"].get(binding.time_var or "", ""), "", language)
        later_when = human_period(rows[-1]["map"].get(binding.time_var or "", ""), "", language)
        if language == "is":
            sentence += f" Það er breyting úr {earlier} ({earlier_when}) í {later} ({later_when})."
        else:
            sentence += f" That is the change from {earlier} ({earlier_when}) to {later} ({later_when})."
    if derived and derived["name"] == "share_percent" and len(rows) >= 2:
        part = format_stat(rows[0]["value"], language)
        whole = format_stat(rows[1]["value"], language)
        if language == "is":
            sentence += f" Hlutinn er {part} af {whole}."
        else:
            sentence += f" The part is {part} of {whole}."
    if derived and derived["name"] == "rebase" and len(rows) >= 2:
        base = format_stat(rows[0]["value"], language)
        target = format_stat(rows[1]["value"], language)
        if language == "is":
            sentence += f" Útreikningurinn tekur {target} á móti grunninum {base}."
        else:
            sentence += f" The calculation takes {target} against the base period value {base}."
    if preliminary:
        if language == "is":
            sentence += " Útgáfan merkir töluna sem bráðabirgðatölu."
        else:
            sentence += " The release marks the figure as preliminary."
    row_notes = [note.split(":", 1)[1].strip() for note in binding.notes if note.startswith("row used:")]
    # A digit in the label would be a second figure the number check has not
    # allowed. The label is already in the sentence when it has no digit.
    if row_notes and not re.search(r"\d", row_notes[0]):
        shown = row_notes[0]
        if language == "is":
            sentence += f" Röðin sem er notuð er {shown}."
        else:
            sentence += f" The row used is {shown}."
    if any("latest period" in note for note in binding.notes):
        if language == "is":
            sentence += " Ekkert tímabil var nefnt, svo nýjasta tímabilið í töflunni er notað."
        else:
            sentence += " No period was named, so the latest period in the table is used."
    sentence += _citation(language, edition, binding, rows, derived)
    from grund.bind2 import attach_derivation

    derived_from = attach_derivation(binding, edition, rows, derived)
    if derived_from is not None and derived_from.sentence(language) not in sentence:
        sentence += " " + derived_from.sentence(language)
    return sentence


def _citation(language: str, edition: Edition, binding: Binding, rows: list[dict], derived: dict | None) -> str:
    """The sentence itself names the table and the link."""
    url = edition.url or ""
    match = re.search(r"([A-Za-z]{3}\d{4,5})\.px", url)
    table = match.group(1) if match else ""
    if not table and not url:
        return ""
    calculated = bool(derived and derived.get("name") in {"yoy_pct", "share_percent", "difference", "rebase"}) or binding.operation in {
        "difference",
        "yoy_pct",
        "share",
        "sum",
    }
    filters = []
    for row in rows[:2]:
        for label in row.get("labels") or []:
            text = str(label.get("label") or "")
            if text and text not in filters and not re.search(r"\d", text):
                filters.append(text)
    period = ""
    if binding.time_codes:
        period = "–".join(str(code) for code in binding.time_codes[:2])
    return " " + source_line(language, table or None, filters[:4], period, url, "", calculated)


def _period_phrase(binding: Binding, edition: Edition, rows: list[dict], language: str) -> str:
    if binding.operation in {"yoy_pct", "difference"} and len(rows) >= 2:
        later = rows[-1]["map"].get(binding.time_var or "", "")
        variable = edition.variable(binding.time_var or "")
        label = variable.label(later) if variable else later
        return human_period(later, label, language)
    if binding.operation == "rebase" and binding.target_code:
        variable = edition.variable(binding.time_var or "")
        label = variable.label(binding.target_code) if variable else binding.target_code
        return human_period(binding.target_code, label, language)
    if rows:
        code = rows[0]["map"].get(binding.time_var or "", "")
        variable = edition.variable(binding.time_var or "")
        label = variable.label(code) if variable else code
        return human_period(code, label, language)
    return "the latest period" if language == "en" else "nýjasta tímabilinu"


def _clean_filter(text: str) -> str:
    folded = " ".join((text or "").split())
    return folded[:80]


def source_line(
    language: str,
    table_id: str | None,
    filters: list[str],
    period: str,
    url: str,
    updated: str,
    calculated: bool,
) -> str:
    """Plain-language citation. Appended after the cell-claim rail has passed.

    A difference, share, or sum is Grund's calculation from the cells. The
    table's own figure is the Hagstofa source. CC BY asks that a transformed
    number not be credited to Statistics Iceland as if they published it.
    """
    shown_filters = ", ".join(_clean_filter(item) for item in filters if item) or (
        "engin sía" if language == "is" else "no extra filter"
    )
    when = period or ("ótilgreint" if language == "is" else "unspecified")
    table = table_id or ("óþekkt tafla" if language == "is" else "unknown table")
    stamp = ""
    if updated:
        stamp = f" Uppfært {updated}." if language == "is" else f" Updated {updated}."
    link = f" {url}" if url else ""
    if language == "is":
        if calculated:
            return f"Reiknað af Grund úr reitum töflu {table} ({shown_filters}), tímabil {when}.{stamp}{link}"
        return f"Tafla {table}, síur {shown_filters}, tímabil {when}.{stamp}{link}"
    if calculated:
        return f"Calculated by Grund from cells of {table} ({shown_filters}), period {when}.{stamp}{link}"
    return f"Table {table}, filters {shown_filters}, period {when}.{stamp}{link}"


def refusal_sources(language: str, candidates: list[dict] | None) -> str:
    """The tables a refusal looked at, each named and linked. No figure."""
    bits = []
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        table_id = str(item.get("table_id") or "").strip()
        title = _clean_filter(str(item.get("title") or ""))
        if title == table_id:
            title = ""
        url = str(item.get("web_url") or item.get("api_url") or item.get("url") or "")
        label = " ".join(part for part in (table_id, title) if part)
        if not label and not url:
            continue
        bits.append(f"{label} {url}".strip() if url else label)
        if len(bits) >= 4:
            break
    if not bits:
        return ""
    joined = "; ".join(bits)
    if language == "is":
        return f"Töflur sem komu til greina: {joined}."
    return f"Tables considered: {joined}."


def refusal(language: str, kind: str) -> str:
    if kind == "injection":
        if language == "is":
            return "Ég svara aðeins spurningum um töflur Hagstofu Íslands. Ég læt fyrirmæli í textanum ekki breyta því."
        return "I only answer questions about Statistics Iceland tables. Instructions hidden in the text do not change that."
    if kind == "clarify_month":
        if language == "is":
            return "Vísitala neysluverðs er birt í hverjum mánuði. Nefndu mánuðinn, eða segðu að þú viljir ársmeðaltalið."
        return "The consumer price index is published every month. Name the month, or say that you want the annual average."
    if kind == "clarify":
        if language == "is":
            return "Ég næ ekki að velja eina töflu án þess að giska. Tilgreindu tímabil, svæði eða hvort þú eigir við sveitarfélag eða landshluta."
        return "I can't choose one table without guessing. Name the period, the area, or whether you mean a municipality or a region."
    if kind == "out_of_scope":
        if language == "is":
            return (
                "Þetta er ekki meðal viðfangsefna í töflum Hagstofu Íslands sem þessi efnisskrá nær yfir. "
                "Ég svara útgefinni tölu þegar spurningin nefnir viðfangsefnið og tímabilið, "
                "til dæmis mannfjölda, verðlag eða vinnumarkað."
            )
        return (
            "That is not among the subjects in the Statistics Iceland tables this index covers. "
            "I can answer a published figure when you name the subject and the period, "
            "for example population, prices, or the labour market."
        )
    if language == "is":
        return (
            "Ég get ekki svarað þessu út frá útgefnum töflum Hagstofu Íslands. "
            "Ég nefni tölu aðeins þegar hún kemur úr reit í PxWeb eða úr útreikningi á þeim reitum."
        )
    return (
        "I can't answer that from a published Statistics Iceland table. "
        "I only state a figure when it comes from a PxWeb cell or from a calculation on those cells."
    )
