"""Deterministic question frame. No model calls.

A frame names the measure, the subject, the filters (sex, age band, region,
municipality, sector, and the related origin or citizenship split), the
period, and the operation. Icelandic inflection goes through the installed
islenska database. "now" and "latest", and a question that names no period,
resolve to the newest period the chosen table publishes.

GRUND_FRAME defaults off. Nothing here runs unless that flag is on.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from grund_index.textutil import fold

_FRAME_UNSET = object()
_CURRENT: dict[str, object] = {"frame": _FRAME_UNSET}


def frame_enabled() -> bool:
    return os.environ.get("GRUND_FRAME", "").strip().lower() in {"1", "true", "yes", "on"}


def current_frame() -> "QuestionFrame | None":
    frame = _CURRENT.get("frame", _FRAME_UNSET)
    if frame is _FRAME_UNSET or frame is None:
        return None
    return frame  # type: ignore[return-value]


def push_frame(frame: "QuestionFrame | None"):
    previous = _CURRENT.get("frame", _FRAME_UNSET)
    _CURRENT["frame"] = frame
    return previous


def reset_frame(token) -> None:
    _CURRENT["frame"] = token


_MONTHS = {
    "january": 1, "jan": 1, "januar": 1, "janury": 1,
    "february": 2, "feb": 2, "februar": 2,
    "march": 3, "mar": 3, "mars": 3,
    "april": 4, "apr": 4,
    "may": 5, "mai": 5,
    "june": 6, "jun": 6, "juni": 6,
    "july": 7, "jul": 7, "juli": 7,
    "august": 8, "aug": 8, "agust": 8,
    "september": 9, "sep": 9, "sept": 9, "september": 9, "septmber": 9,
    "october": 10, "oct": 10, "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12, "desember": 12, "des": 12,
}
_MONTH_NAME_EN = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December",
}
_MONTH_NAME_IS = {
    1: "janúar", 2: "febrúar", 3: "mars", 4: "apríl", 5: "maí", 6: "júní",
    7: "júlí", 8: "ágúst", 9: "september", 10: "október", 11: "nóvember", 12: "desember",
}

# Observed misspellings and accent-stripped forms. A token is replaced only
# when it is not already a month name or a real lexicon word.
_TYPOS = {
    "peopl": "people",
    "janury": "january",
    "septmber": "september",
    "indx": "index",
    "unemploymnet": "unemployment",
    "unemployement": "unemployment",
    "domestc": "domestic",
    "domesticc": "domestic",
    "visitla": "vísitala",
    "visitala": "vísitala",
    "neysluverds": "neysluverðs",
    "launavisitalan": "launavísitalan",
    "launavisitala": "launavísitala",
    "landsframleiddsla": "landsframleiðsla",
    "landsframleidsla": "landsframleiðsla",
    "byggingarvisitla": "byggingarvísitala",
    "byggingarvisitala": "byggingarvísitala",
    "bulding": "building",
    "babis": "babies",
    "islndi": "íslandi",
    "islandi": "íslandi",
    "faeddust": "fæddust",
    "morg": "mörg",
    "born": "börn",
    "bua": "búa",
    "arid": "árið",
    "arsfjordungi": "ársfjórðungi",
    "hofudborgarsvaedinu": "höfuðborgarsvæðinu",
    "hofudborgarsvaedi": "höfuðborgarsvæði",
    "sudurlandi": "suðurlandi",
    "nordurlandi": "norðurlandi",
}

_LEXICON = {
    "people", "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december", "index", "unemployment",
    "domestic", "building", "babies", "iceland", "consumer", "price", "wage",
    "gross", "product", "population", "women", "woman", "inflation", "exports",
    "imports", "overnight", "births", "children", "immigrants", "balance",
    "quarter", "capital", "region", "average", "annual", "change",
}

_STOP = {
    "what", "was", "were", "the", "and", "for", "from", "with", "that", "this",
    "how", "many", "much", "did", "does", "there", "were", "been", "have",
    "has", "its", "not", "too", "high", "low", "now", "latest", "most", "recent",
    "hvad", "hver", "hve", "hversu", "var", "voru", "eru", "sem", "fyrir",
    "med", "vid", "eftir", "til", "fra", "um", "the", "of", "in", "on", "by",
    "a", "an", "to", "or", "og", "er", "en", "ad", "af", "their", "them",
    "hvert", "hver", "haekkadi", "haekkad", "haekka", "faeddust", "faeddist",
    "fluttu", "flutti", "immigrated", "unemployed", "netto", "stort", "landsmanna",
    "older", "eldri", "yesterday", "gaer", "visitors", "visitor",
    "people", "person", "persons", "folk", "ibu", "ibuar", "ibuafjoldi",
    "lived", "live", "lives", "bua", "bjuggu", "bjugum", "byr", "margir",
    "margar", "margt", "morg", "many", "number", "fjoldi", "total",
    "iceland", "island", "islandi", "islensku", "icelands",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "januar", "februar",
    "mars", "juni", "juli", "agust", "oktober", "desember", "mai",
    "quarter", "arsfjordung", "arsfjordungi", "second", "first", "third", "fourth",
    "odrum", "fyrsta", "year", "arid", "arinu", "years", "old", "olds",
    "percent", "prosent", "percentage", "points", "point", "stig", "share",
    "hlutfall", "hlutdeild", "rate", "index", "visitala", "change", "breyting",
    "arsbreyting", "annual", "average", "arsmedal", "arsmedaltal",
    "registered", "accommodation", "skradum", "skradra", "gististodum",
    "goods", "services", "voru", "thjonustu", "thjonusta", "and", "alls",
}

_FEMALE = {
    "women", "woman", "female", "females", "girl", "girls",
    "konur", "kona", "kvenna", "konum", "konu", "kvenkyns", "stulkur", "stulka",
}
_MALE = {
    "men", "man", "male", "males", "boy", "boys",
    "karlar", "karl", "karla", "korlum", "drengir", "drengur", "drengja",
}

_REGIONS = (
    # "the capital" is the city. "capital area" is not one published region.
    ("capital", ("capital region", "hofudborgarsvaedi", "hofudborgarsvaedinu", "hofudborgarsvaedis")),
    ("southwest", ("southwest", "sudurnes", "sudurnesjum")),
    ("westfjords", ("westfjords", "west fjords", "vestfirdir", "vestfirdum")),
    ("northwest", ("northwest", "nordurland vestra", "nordurlandi vestra")),
    ("northeast", ("northeast", "nordurland eystra", "nordurlandi eystra")),
    ("east", ("austurland", "austurlandi", "east")),
    ("west", ("vesturland", "vesturlandi", "west")),
    ("south", ("sudurland", "sudurlandi", "south")),
)

_REGION_LABELS = {
    "capital": ("Capital region", "Höfuðborgarsvæði", "Höfuðborgarsvæðið"),
    "south": ("South", "Suðurland"),
    "northeast": ("Northeast", "Norðurland eystra"),
    "northwest": ("Northwest", "Norðurland vestra"),
    "east": ("East", "Austurland"),
    "west": ("West", "Vesturland"),
    "westfjords": ("Westfjords", "Vestfirðir"),
    "southwest": ("Southwest", "Suðurnes"),
}


@dataclass
class FramePeriod:
    kind: str = "latest"  # point, range, latest, relative
    year: int | None = None
    month: int | None = None
    quarter: int | None = None
    end_year: int | None = None
    end_month: int | None = None
    relative: str = ""
    implicit: bool = False

    def as_dict(self) -> dict:
        payload: dict = {"kind": "latest" if self.kind in {"latest", "relative"} and not self.year else self.kind}
        if self.kind == "point" and self.year:
            payload = {"kind": "point", "year": self.year}
            if self.month:
                payload["month"] = self.month
            if self.quarter:
                payload["quarter"] = self.quarter
        elif self.kind == "range" and self.year and self.end_year:
            payload = {
                "kind": "range",
                "start": {"year": self.year, "month": self.month},
                "end": {"year": self.end_year, "month": self.end_month},
            }
        elif self.kind == "relative":
            payload = {"kind": "latest", "relative": self.relative}
        else:
            payload = {"kind": "latest"}
        return payload


@dataclass
class QuestionFrame:
    text: str
    language: str = "en"
    measure: str = ""
    subject: str = ""
    operation: str = "level"
    sex: str = ""
    age_exact: str = ""
    age_open: str = ""
    region: str = ""
    municipality: str = ""
    municipality_surface: str = ""
    sector: str = ""
    origin: str = ""
    citizenship: str = ""
    period: FramePeriod = field(default_factory=FramePeriod)
    pipeline_text: str = ""
    use: bool = False
    blocked: str = ""
    leftovers: list[str] = field(default_factory=list)
    corrected: str = ""
    unresolved_place: bool = False

    @property
    def implicit_period(self) -> bool:
        return bool(self.period.implicit) and not self.blocked

    def filters(self) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        if self.sex:
            found["sex"] = _sex_aliases(self.sex)
        if self.age_exact:
            found["age"] = [self.age_exact, f"{self.age_exact} years", f"{self.age_exact} ára"]
        if self.region:
            found["region"] = [fold(name) for name in _REGION_LABELS.get(self.region, (self.region,))]
        if self.municipality:
            found["municipality"] = _place_aliases(self.municipality)
        if self.sector:
            found["sector"] = _place_aliases(self.sector)
        if self.origin:
            found["origin"] = ["immigrant", "innflytjandi", "innflytjendur"]
        if self.citizenship:
            found["citizenship"] = ["foreigners", "foreign", "utlendingar", "erlendir", "erlendra"]
        return found

    def rail_payload(self) -> dict:
        return {
            "measure": self.measure,
            "subject": self.subject,
            "operation": self.operation,
            "filters": self.filters(),
            "period": self.period.as_dict(),
            "implicit_period": self.implicit_period,
        }

    def preference(self, table) -> int:
        if not self.use or table is None:
            return 0
        edition = _edition(table, self.language) or _edition(table, "en") or _edition(table, "is")
        if edition is None:
            return 0
        title = fold(f"{getattr(edition, 'title', '')} {' '.join(getattr(edition, 'path_texts', []) or [])}")
        score = 0
        for hint in _MEASURE_HINTS.get(self.measure, ()):
            if hint in title:
                score += 6
        if self.measure == "population" and not self._geo_filter() and not self.sex and not self.age_exact:
            real_title = fold(getattr(edition, "title", ""))
            if "key figures" in real_title or "lykiltolur" in real_title:
                score += 40
            if self.age_exact and ("sex and age" in title or "kyni og aldri" in title) and "landshlut" not in title and "region" not in title:
                score += 25
            if (self.sex or self.age_exact) and not self.origin and (
                "sex and age" in title or "kyni og aldri" in title
            ) and not any(mark in title for mark in ("landshlut", "region", "sveitar", "origin", "bakgrunn", "municipality")):
                score += 18
            if any(mark in title for mark in ("country of", "citizenship", "rikisfang", "faedingarland", "urban", "thettbyl", "degree of")):
                score -= 24
            nav = fold(" ".join(getattr(edition, "path_texts", []) or []))
            if (self.sex or self.age_exact) and ("overview" in nav or "yfirlit" in nav) and (
                "sex and age" in title or "kyni og aldri" in title
            ):
                score += 14
            if not self.origin and any(mark in title for mark in ("bakgrunn", "origin", "manntal", "census")):
                score -= 18
            if any(mark in title for mark in ("vinnumarkad", "labour force", "by status")):
                score -= 22
            if not self.region and not self.municipality and any(
                mark in title for mark in ("landshlut", "by region", "sveitarfelag", "municipality")
            ):
                score -= 30
        asked = fold(self.text)
        if ("soguleg" in title or "historical" in title) and "soguleg" not in asked and "historical" not in asked:
            score -= 30
        if self.measure == "cpi":
            if self.period.month and ("change" in title or "breyting" in title):
                score += 28
            elif self.period.year and not self.period.month and ("annual average" in title or "arsmedal" in title):
                score += 28
            elif self.period.implicit and ("change" in title or "breyting" in title):
                score += 16
        if self.measure == "wage_index" and ("wage index" in title or "launavisit" in title):
            score += 24
        if self.measure in {"unemployment_rate", "unemployment_count"}:
            quarterly = "quarter" in title or "arsfjordung" in title or "fjordung" in title
            yearly = ("by year" in title or "eftir arum" in title) and not quarterly
            if self.period.quarter and quarterly:
                score += 28
            elif self.period.year and not self.period.quarter and yearly:
                score += 28
        if self.measure in {"gdp", "exports_gs", "exports_goods", "imports_gs"} and (
            "landsframleid" in title or "gross domestic" in title or "thjodartekj" in title
        ):
            score += 30
        if self.measure == "building_cost" and ("byggingarvisit" in title or "building cost" in title):
            score += 30
        if self.measure in {"overnight", "arrivals"} and ("gistinaet" in title or "overnight" in title):
            score += 24
        if self.measure == "births" and ("faed" in title or "birth" in title):
            score += 20
        if self.measure == "immigrant_stock" and ("origin" in title or "bakgrunn" in title):
            score += 28
        if self.measure in {"immigration_flow", "net_migration"} and ("migration" in title or "buferlaflutn" in title):
            score += 28
        score += self._filter_score(edition)
        if self.municipality and _wider_geo(edition):
            score -= 40
        if self.municipality:
            noisy = any(
                mark in title
                for mark in (
                    "rikisfang", "citizenship", "ofmat", "breytt", "manntal", "census",
                    "bakgrunn", "origin", "postcode", "postnumer",
                )
            )
            if not noisy and ("sveitarfelag" in title or "municipality" in title):
                score += 22
            path = fold(" ".join(getattr(edition, "path_texts", []) or []))
            if "other areas" in path or "onnur" in path or "1950" in title:
                score -= 18
            if path.endswith("municipalities") or path.endswith("sveitarfelog"):
                score += 10
        if self.measure in {"gdp", "exports_gs", "exports_goods", "imports_gs"} and _gdp_line(edition):
            score += 28
        if self.measure == "immigrant_stock" and ("bakgrunn" in title or " by origin" in title or "origin," in title):
            if "manntal" not in title and "census" not in title:
                score += 18
        if self.measure == "cpi" and self.operation == "change":
            if ("breyting" in title or "changes" in title) and "samraemd" not in title and "harmon" not in title:
                score += 18
        if self.measure == "wage_index":
            if any(mark in title for mark in ("sector", "atvinnugrein", "quarterly", "arsfjordung", "fjordung")):
                score -= 18
            if "manud" in title or "by month" in title:
                score += 14
        year = self.period.year or self.period.end_year
        if year and not _covers_year(edition, year):
            score -= 45
        title_years = [int(item) for item in re.findall(r"(?:19|20)\d{2}", title)]
        if year and title_years and max(title_years) < int(year) and not _covers_year(edition, year):
            score -= 45
        elif year and title_years and max(title_years) < int(year):
            # A title that ends before the asked year, with no year codes, is a closed series.
            try:
                coded = set(edition.years())
            except Exception:
                coded = set()
            if not coded:
                score -= 45
        if self.measure == "immigrant_stock":
            if "mannfjold" in title or "population by origin" in title:
                score += 14
            if any(mark in title for mark in ("kosning", "election", "participation", "thahttaka")):
                score -= 24
        if self.measure == "cpi" and any(mark in title for mark in ("breakdown", "contribution", "lidaskipt", "framlag")):
            score -= 16
        if self.measure in {"gdp", "exports_gs", "exports_goods", "imports_gs"}:
            if ("thjodartekj" in title or "national income" in title) and (
                "landsframleid" in title or "gross domestic product" in title
            ):
                score += 16
            if "constant" in title or "fast verdlag" in title:
                score -= 22
            if "overview" in title or title.startswith("yfirlit"):
                score -= 12
        if self.measure == "population" and self.region:
            blob = title + " " + fold(" ".join(getattr(edition, "path_texts", []) or []))
            if any(mark in blob for mark in ("labour", "vinnumarkad", "quarter", "arsfjordung", "faeding", "migration", "flutning")):
                score -= 22
            if "landshlut" in title or "by regions" in title:
                score += 12
        # 1 January is the stock. "Meðalmannfjöldi" is the average over the year.
        if self.measure == "population" and (self.period.month == 1 or re.search(r"\b1\s*\.?\s*jan", asked)):
            if any(mark in title for mark in ("medalmannfjold", "average annual", "average population")):
                score -= 40
            if "1 januar" in title or "1. januar" in title:
                score += 16
        if self.measure in {"unemployment_rate", "unemployment_count"}:
            asked_participation = any(
                mark in asked for mark in ("atvinnuthatttaka", "activity rate", "employment rate", "starfandi")
            )
            participation_table = any(
                mark in title for mark in ("atvinnuthatttaka", "activity rate", "employment rate")
            )
            if not asked_participation and participation_table:
                score -= 28
            if not asked_participation and not participation_table and (
                "unemployment by" in title or "atvinnulaus" in title
            ):
                score += 22
        if self.measure in {"exports_gs", "imports_gs"}:
            if any(mark in title for mark in ("utanrikisverslun", "external trade", "customs")):
                score -= 36
            if any(mark in title for mark in ("thjodhags", "national account", "landsframleid")):
                score += 12
        return score

    def _geo_filter(self) -> bool:
        return bool(self.municipality or self.region)

    def _filter_score(self, edition) -> int:
        score = 0
        if self.municipality:
            if _match_place(edition, "municipality", self.municipality):
                score += 45
            elif _has_role(edition, "municipality"):
                score -= 8
            else:
                score -= 6
        if self.region:
            if _match_region(edition, self.region):
                score += 35
            elif _has_role(edition, "region"):
                score -= 4
        if self.origin and _match_origin(edition):
            score += 20
        if self.sex and _has_role(edition, "sex"):
            score += 8
        return score

    def needs_supplement(self) -> bool:
        if not self.use:
            return False
        return bool(
            self.measure
            in {
                "population", "cpi", "wage_index", "unemployment_rate", "unemployment_count",
                "gdp", "exports_gs", "exports_goods", "imports_gs", "overnight", "arrivals",
                "births", "immigrant_stock", "immigration_flow", "net_migration", "building_cost",
            }
        )

    def supplement_min(self) -> int:
        return 18

    def decide(self, variable):
        """A code list, None to leave the binder, or 'reject' to skip the table."""
        if not self.use:
            return None
        role = variable_role(variable)
        if not role or _is_time_role(variable):
            return None
        if role == "sex" and self.operation == "share":
            return None
        if role == "sex" and self.sex:
            code = _match_sex(variable, self.sex)
            return [code] if code else "reject"
        if role == "age" and self.age_exact:
            code = _match_age(variable, self.age_exact)
            return [code] if code else "reject"
        if role == "municipality" and self.municipality:
            code = _match_place_variable(variable, self.municipality)
            return [code] if code else "reject"
        if role == "region" and self.region:
            code = _match_region_variable(variable, self.region)
            return [code] if code else "reject"
        if role == "origin" and self.origin:
            code = _match_label(variable, ("immigrant", "innflytjandi"))
            return [code] if code else "reject"
        if role == "citizenship" and self.citizenship:
            code = _match_label(variable, ("foreigners", "foreign", "utlending", "erlend"))
            return [code] if code else "reject"
        if role == "sector" and self.sector:
            code = _match_place_variable(variable, self.sector)
            return [code] if code else None
        if role == "migration" and self.measure in {"immigration_flow", "net_migration"}:
            code = _match_migration(variable, self.measure)
            return [code] if code else "reject"
        if role == "unit":
            code = _match_unit(variable, self)
            return [code] if code else None
        if role == "category":
            code = _match_category(variable, self)
            return [code] if code else None
        if role == "multiplicity" and self.measure == "births":
            code = _match_total(variable)
            return [code] if code else None
        if role == "month" and self.period.month is None and self.measure in {"overnight", "arrivals"}:
            code = _match_total(variable)
            return [code] if code else None
        if self._force_total(role):
            code = _match_total(variable)
            return [code] if code else None
        if role == "municipality" and self.municipality:
            return "reject"
        if self.municipality and role == "municipality":
            return "reject"
        return None

    def reject_table(self, edition) -> bool:
        """True when this edition cannot express a filter the question named."""
        if not self.use or edition is None:
            return False
        if self.measure == "population" and not self.municipality and not self.region:
            if _has_role(edition, "municipality") or _has_role(edition, "region") or _wider_geo(edition):
                return True
        if self.municipality and not _match_place(edition, "municipality", self.municipality):
            return True
        if self.region and not _match_region(edition, self.region):
            if _has_role(edition, "region") or self.measure == "population":
                return True
        if self.sex and self.operation != "share" and self.measure in {
            "population", "unemployment_rate", "unemployment_count", "immigrant_stock"
        }:
            if not _has_role(edition, "sex"):
                return True
        if self.measure == "births":
            title = fold(getattr(edition, "title", ""))
            if any(mark in title for mark in ("mortality", "daudi", "andvana", "fetal", "infant death")):
                return True
        if self.measure in {"exports_gs", "imports_gs"}:
            title = fold(getattr(edition, "title", "") + " " + " ".join(getattr(edition, "path_texts", []) or []))
            # A commodity breakdown in tonnes is not the national-accounts line
            # for goods and services.
            if any(mark in title for mark in ("voruflokk", "commodit", "vinnslugrein", "branches of processing")):
                return True
        if self.age_exact and self.measure == "population":
            if not any(
                variable_role(variable) == "age" and _match_age(variable, self.age_exact)
                for variable in getattr(edition, "variables", []) or []
            ):
                return True
        if self.origin and not _match_origin(edition):
            return True
        if self.measure in {"immigration_flow", "net_migration"} and not _has_role(edition, "migration"):
            return True
        return False

    def _force_total(self, role: str) -> bool:
        if role == "sex" and self.sex:
            return False
        if role == "age" and self.age_exact:
            return False
        if role == "region" and self.region:
            return False
        if role == "citizenship" and self.citizenship:
            return False
        if self.measure == "population" and (self.municipality or self.region):
            return role in {"sex", "age"}
        if self.measure == "immigrant_stock":
            return role in {"sex", "age"}
        if self.measure in {"overnight", "arrivals"}:
            return role in {"region", "citizenship"}
        if self.measure == "births":
            return role in {"sex"}
        if self.measure in {"immigration_flow", "net_migration"}:
            return role in {"sex", "citizenship"}
        if self.measure in {"unemployment_rate", "unemployment_count"}:
            return role in {"sex", "region"}
        return False


_MEASURE_HINTS = {
    "population": ("population", "mannfjold", "mannfjoldi", "inhabitants"),
    "cpi": ("consumer price", "neysluverd", "visitala neyslu"),
    "wage_index": ("wage index", "launavisit"),
    "unemployment_rate": ("unemployment", "atvinnuleys"),
    "unemployment_count": ("unemployment", "atvinnuleys"),
    "gdp": ("gross domestic", "landsframleid", "verg landsframleid"),
    "exports_gs": ("landsframleid", "gross domestic", "thjodartekj"),
    "exports_goods": ("landsframleid", "gross domestic"),
    "imports_gs": ("landsframleid", "gross domestic"),
    "overnight": ("overnight", "gistinaet"),
    "arrivals": ("overnight", "gistinaet", "gestakom"),
    "births": ("birth", "faed", "faeding"),
    "immigrant_stock": ("origin", "bakgrunn", "innflytj"),
    "immigration_flow": ("migration", "buferlaflutn"),
    "net_migration": ("migration", "buferlaflutn"),
    "building_cost": ("building cost", "byggingarvisit"),
}


def variable_role(variable) -> str:
    key = fold(f"{getattr(variable, 'text', '')} {getattr(variable, 'code', '')}")
    if any(word in key for word in ("kyn", "sex", "gender")) and "kynslod" not in key:
        return "sex"
    if re.search(r"\b(age|aldur)\b", key):
        return "age"
    if "sveitarfelag" in key or "municipality" in key:
        return "municipality"
    if "landshlut" in key or "landsvaed" in key or key.strip() in {"region"}:
        return "region"
    if "thjoderni" in key or "citizenship" in key or "rikisfang" in key:
        return "citizenship"
    if "bakgrunn" in key or "origin" in key:
        return "origin"
    if "flutning" in key or "migration" in key:
        return "migration"
    if "atvinnugrein" in key or re.search(r"\b(sector|industry)\b", key):
        return "sector"
    if "barna" in key or "children" in key:
        return "multiplicity"
    if re.search(r"\b(manudur|month)\b", key) and not getattr(variable, "time", False):
        return "month"
    if any(word in key for word in ("eining", "unit", "unity", "lidur", "item")):
        return "unit"
    if any(word in key for word in ("skipting", "category", "categories")):
        return "category"
    return ""


def _is_time_role(variable) -> bool:
    if getattr(variable, "time", False):
        return True
    values = list(getattr(variable, "values", []) or [])
    if len(values) < 3:
        return False
    hits = 0
    for code, _label in values:
        if re.fullmatch(r"A?(?:19|20)\d{2}(?:M\d{2}|Q\d)?", str(code), re.I):
            hits += 1
    return hits >= max(3, len(values) // 2)


def frame_question(text: str) -> QuestionFrame:
    raw = text or ""
    language = _language(raw)
    corrected = _correct(raw, language)
    expanded = _expand(corrected, language)
    frame = QuestionFrame(text=raw, language=language, corrected=expanded)
    folded = fold(expanded)
    frame.period = _period(folded, expanded)
    frame.operation = _operation(folded)
    frame.sex = _sex(folded)
    frame.age_exact, frame.age_open = _age(folded, expanded)
    frame.region = _region(folded)
    frame.municipality, frame.municipality_surface = _municipality(expanded, folded)
    frame.sector = _sector(folded)
    frame.origin, frame.citizenship = _origin_citizenship(folded)
    frame.measure = _measure(folded, frame)
    frame.subject = _subject(frame)
    if _capital_area(folded) and not frame.region:
        frame.unresolved_place = True
        frame.region = ""
        frame.municipality = ""
    if _opinion(folded):
        frame.blocked = "opinion"
    elif _weather(folded) or _mars(folded):
        frame.blocked = "non_statistics"
    elif _bare_age_span(folded, frame):
        frame.blocked = "age_span"
    elif frame.measure == "trade_balance" and frame.period.month is None:
        frame.blocked = "month_missing"
    elif _future(folded):
        frame.blocked = ""
        frame.measure = ""
    frame.leftovers = _leftovers(folded, frame)
    frame.use = _usable(frame)
    frame.pipeline_text = _pipeline(frame, expanded) if frame.use else ""
    return frame


def latest_period_label(language: str, code: str) -> str:
    shown = str(code or "").strip()
    if language == "is":
        return f"nýjasta birta tímabil: {shown}"
    return f"latest published period: {shown}"


def annotate_latest(result: dict, frame: QuestionFrame | None) -> dict:
    if not frame or not frame.use or not frame.implicit_period:
        return result
    if not result or result.get("refused") or result.get("value") in (None, ""):
        return result
    code = _result_period(result)
    if not code:
        return result
    label = latest_period_label(result.get("language") or frame.language, code)
    answer = str(result.get("answer") or "")
    if label in answer:
        return result
    updated = dict(result)
    updated["answer"] = (answer.rstrip() + " " + label).strip()
    updated["latest_period"] = code
    return updated


def order_hits(catalogue, hits, frame: QuestionFrame | None):
    if frame is None or not frame.use:
        return hits
    pool = list(hits or [])
    if frame.needs_supplement() and catalogue is not None:
        best = None
        best_score = 0
        present = {getattr(hit.table, "id", "") for hit in pool}
        for table in getattr(catalogue, "tables", []) or []:
            score = frame.preference(table)
            if getattr(table, "id", "") in present:
                score += 1
            if score > best_score:
                best_score = score
                best = table
        if best is not None and best_score >= frame.supplement_min() and getattr(best, "id", "") not in present:
            from grund_index.catalogue import Hit

            pool = [Hit(table=best, score=10000.0, bm25=0.0, cosine=0.0, value_boost=0.0), *pool]
    ranked = []
    for index, hit in enumerate(pool):
        pref = frame.preference(hit.table)
        score = hit.score + (pref * 100 if pref > 0 else 0)
        if score != hit.score:
            from grund_index.catalogue import Hit

            hit = Hit(table=hit.table, score=score, bm25=hit.bm25, cosine=hit.cosine, value_boost=hit.value_boost)
        ranked.append((pref, index, hit))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked]


def impose_frame(edition, chosen: dict) -> dict | None:
    """Apply the frame to a binder selection. None means this table cannot answer."""
    frame = current_frame()
    if frame is None or not frame.use:
        return chosen
    if frame.reject_table(edition):
        return None
    updated = dict(chosen)
    for variable in getattr(edition, "variables", []) or []:
        if _is_time_role(variable):
            continue
        decision = frame.decide(variable)
        if decision == "reject":
            return None
        if decision:
            updated[variable.code] = list(decision)
    return updated


def frame_time_codes(variable, parsed) -> list[str] | None:
    """Relative periods, once the table's own codes are known. None leaves the binder."""
    frame = current_frame()
    if frame is None or not frame.use:
        return None
    if frame.period.kind != "relative":
        return None
    codes = [str(code) for code, _label in (getattr(variable, "values", []) or [])]
    if not codes:
        return None
    if frame.period.relative == "previous":
        if len(codes) < 2:
            return [codes[-1]]
        return [codes[-2]]
    return None


def _language(text: str) -> str:
    if any(char in text for char in "áéíóúýþðæöÁÉÍÓÚÝÞÐÆÖ"):
        return "is"
    folded = fold(text)
    hints = {
        "hve", "hvad", "hver", "hversu", "hvert", "arid", "bjuggu", "bua", "voru",
        "konur", "karlar", "visitala", "atvinnuleysi", "arsfjordungi", "faeddust",
    }
    words = set(re.findall(r"[a-z0-9]+", folded))
    if len(words & hints) >= 2:
        return "is"
    return "en"


def _correct(text: str, language: str) -> str:
    def swap(match: re.Match) -> str:
        word = match.group(0)
        key = fold(word)
        if key in _MONTHS and key not in _TYPOS:
            return word
        if key in _TYPOS:
            if language == "en" and key in {"born", "bua", "morg", "arid", "islandi"}:
                return word
            return _TYPOS[key]
        if key in _LEXICON or key in _STOP or len(key) < 5:
            return word
        if _is_real_icelandic(word):
            return word
        fixed = _fuzzy(key)
        return fixed if fixed else word

    return re.sub(r"[A-Za-zÁÉÍÓÚÝÞÆÖáéíóúýþæöð]+", swap, text)


def _is_real_icelandic(word: str) -> bool:
    if len(word) < 4:
        return False
    try:
        from grund_lang.binaccess import lexicon_lemma
    except Exception:
        return False
    found = lexicon_lemma(word)
    return bool(found and found[0])


def _fuzzy(token: str) -> str:
    if len(token) < 5:
        return ""
    best = ""
    best_distance = 3 if len(token) >= 8 else 2
    for word in _LEXICON:
        distance = _distance(token, word)
        if distance < best_distance:
            best = word
            best_distance = distance
    if best_distance <= (2 if len(token) >= 8 else 1) and best:
        return best
    return ""


def _distance(left: str, right: str) -> int:
    if abs(len(left) - len(right)) > 2:
        return 9
    previous = list(range(len(right) + 1))
    for i, char in enumerate(left, start=1):
        current = [i]
        for j, other in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (char != other),
            ))
        previous = current
    return previous[-1]


def _expand(text: str, language: str) -> str:
    folded = fold(text)
    if re.search(r"\bq\s*([1-4])\b", folded):
        quarter = re.search(r"\bq\s*([1-4])\b", folded).group(1)
        names = {"1": "first", "2": "second", "3": "third", "4": "fourth"}
        text = re.sub(r"\bq\s*[1-4]\b", names[quarter] + " quarter", text, count=1, flags=re.I)
    text = re.sub(r"\bwhats\b", "what is", text, flags=re.I)
    text = re.sub(r"\bwhat's\b", "what is", text, flags=re.I)
    if language == "is":
        text = re.sub(
            r"\ba\s+([1-4])\s+arsfj\w+",
            lambda match: f"á {('fyrsta', 'öðrum', 'þriðja', 'fjórða')[int(match.group(1)) - 1]} ársfjórðungi",
            text,
            count=1,
            flags=re.I,
        )
    return text


def _period(folded: str, text: str) -> FramePeriod:
    period = FramePeriod()
    if re.search(r"\b(last year|sidasta ar|i fyrra|last month|sidasta manud)\b", folded):
        period.kind = "relative"
        period.relative = "previous"
        period.implicit = False
        return period
    if re.search(r"\b(now|today|latest|most recent|newest|nuna|nyjast\w*|sidast\w*|seinast\w*)\b", folded):
        period.kind = "latest"
        period.implicit = True
    years = [int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", folded)]
    # A base year ("1988=100" or "base 1988") is not the period.
    years = [
        year for year in years
        if not re.search(rf"(?:base|grunn\w*)\s*{year}", folded) and f"{year}=100" not in folded.replace(" ", "")
    ]
    month = None
    for word in re.findall(r"[a-z]+", folded):
        if word in _MONTHS:
            month = _MONTHS[word]
            break
    quarter = None
    numbered = re.search(r"\b([1-4])\s*\.?\s*arsfjordung\w*", folded)
    if numbered:
        quarter = int(numbered.group(1))
    match = re.search(
        r"\b(first|second|third|fourth|1st|2nd|3rd|4th|odrum|fyrsta|annar|thridja|fjorda)\b",
        folded,
    )
    if match and re.search(r"quarter|arsfjordung", folded):
        quarter = {"first": 1, "1st": 1, "fyrsta": 1, "second": 2, "2nd": 2, "odrum": 2, "annar": 2,
                   "third": 3, "3rd": 3, "thridja": 3, "fourth": 4, "4th": 4, "fjorda": 4}.get(match.group(1))
    if len(years) >= 2 and (month or re.search(r"\b(from|fra|til|to)\b", folded)):
        period.kind = "range"
        period.year = years[0]
        period.end_year = years[-1]
        period.month = month
        period.end_month = month
        period.implicit = False
        return period
    if years:
        period.kind = "point"
        period.year = years[-1] if month or quarter else years[0]
        if len(years) == 1:
            period.year = years[0]
        period.month = month
        period.quarter = quarter
        period.implicit = False
        return period
    period.kind = "latest"
    period.implicit = True
    period.month = month
    period.quarter = quarter
    return period


def _operation(folded: str) -> str:
    if _change_denied(folded):
        return "level"
    if re.search(r"\b(inflation|verdbolg\w*)\b", folded) and not _opinion(folded):
        return "change"
    if re.search(
        r"\b(share|proportion|hlutfall|hlutdeild|percent of|percentage of|prosent of|what percentage)\b",
        folded,
    ) or re.search(r"\bhve stort hlutfall\b", folded):
        return "share"
    if re.search(r"\b(by what percent|what percent|annual change|arsbreyting|percent change|prosentubreyting|over the year)\b", folded):
        return "change"
    if re.search(r"\b(by how many points|by how many|um hve morg stig|um hve morg punkt|stig haekk)\b", folded):
        return "difference"
    if re.search(r"\b(difference|mismunur|how many more)\b", folded):
        return "difference"
    if re.search(r"\b(together|samtals)\b", folded) and re.search(r"\b(and|og)\b", folded):
        return "sum"
    if re.search(r"\b(rose|fell|haekk\w*|laekk\w*|increased|decreased)\b", folded) and re.search(r"percent|prosent|percent", folded):
        return "change"
    return "level"


def _sex(folded: str) -> str:
    words = set(re.findall(r"[a-z0-9]+", folded))
    if words & _FEMALE or re.search(r"\b(women|woman|konur|kvenna|konum)\b", folded):
        return "female"
    if words & _MALE:
        return "male"
    return ""


def _age(folded: str, text: str) -> tuple[str, str]:
    if re.search(r"\b(\d{1,3})\s*(?:\+|and older|og eldri|or older|ara og eldri)\b", folded):
        return "", re.search(r"\b(\d{1,3})", folded).group(1)
    match = re.search(r"\b(\d{1,3})\s*[- ]?\s*(?:year[- ]olds?|years? old|ara|ars)\b", folded)
    if match:
        return match.group(1), ""
    match = re.search(r"\baged\s+(\d{1,3})\b", folded)
    if match and not re.search(r"older|eldri", folded):
        return match.group(1), ""
    return "", ""


def _region(folded: str) -> str:
    for name, phrases in _REGIONS:
        for phrase in phrases:
            if " " in phrase:
                if phrase in folded:
                    return name
            elif re.search(rf"\b{re.escape(phrase)}\b", folded):
                # "south" must not win inside a longer match already returned.
                return name
    return ""


def _municipality(text: str, folded: str) -> tuple[str, str]:
    # A capitalised month or "the South" is not a town. Reykjavík is.
    # "the capital" is the city. "capital region" is the region, handled apart.
    if re.search(r"\bon mars\b|\ba mars\b", folded):
        return "", ""
    if "capital region" in folded or "hofudborgarsvaed" in folded or "capital area" in folded:
        pass
    elif re.search(r"\b(the capital|hofudborgin|hofudborginni|hofudborgina)\b", folded):
        return "Reykjavík", "Reykjavík"
    candidates = re.findall(r"[A-ZÁÉÍÓÚÝÞÆÖ][\wÁÉÍÓÚÝÞÆÖáéíóúýþæöð-]{3,}", text)
    candidates += re.findall(r"\b(?:í|i|in|á|a)\s+([A-Za-zÁÉÍÓÚÝÞÆÖáéíóúýþæöð-]{5,})", text)
    seen = set()
    for surface in candidates:
        key = fold(surface)
        if key in seen:
            continue
        seen.add(key)
        if key in _MONTHS or key in _STOP or key in _LEXICON:
            continue
        if key in {"iceland", "island", "islandi", "mars", "january", "total", "table"}:
            continue
        if key.startswith("reykjav"):
            return "Reykjavík", surface
        if any(key == phrase or key.startswith(phrase) for _name, phrases in _REGIONS for phrase in phrases if " " not in phrase):
            continue
        if any(phrase in folded and key in phrase.split() for _name, phrases in _REGIONS for phrase in phrases):
            continue
        town = _known_town(surface)
        if town:
            return town, surface
    if re.search(r"\breykjav", folded):
        return "Reykjavík", "Reykjavík"
    return "", ""


def _known_town(word: str) -> str:
    """A town lemma from BÍN, or empty when the word is not a place."""
    try:
        from grund_lang.binaccess import lexicon_place
    except Exception:
        return ""
    found = lexicon_place(word)
    if not found:
        return ""
    folded = fold(found)
    if folded in {"island", "iceland", "mars"} or folded in _MONTHS:
        return ""
    return found


def _sector(folded: str) -> str:
    match = re.search(r"\b(?:sector|atvinnugrein\w*|industry)\s+([a-z]{4,})", folded)
    if match:
        return match.group(1)
    return ""


def _origin_citizenship(folded: str) -> tuple[str, str]:
    origin = ""
    citizenship = ""
    if re.search(r"\b(immigrants?|innflytjend\w*|innflytjand\w*)\b", folded) and not re.search(
        r"\b(immigrated|fluttu|flutti|immigration to)\b", folded
    ):
        if re.search(r"\b(lived|live|bjuggu|bua|ibuar|on 1|januar)\b", folded) or not re.search(
            r"\b(immigrated|fluttu)\b", folded
        ):
            origin = "immigrant"
    if re.search(r"\b(foreign|foreigners|erlend\w*|utlending\w*)\b", folded):
        citizenship = "foreign"
    return origin, citizenship


def _measure(folded: str, frame: QuestionFrame) -> str:
    if re.search(r"\b(balance of trade|trade balance|voruskiptajofn\w*|voruskipta)\b", folded):
        return "trade_balance"
    if re.search(r"\b(building cost|byggingarvisit\w*)\b", folded):
        return "building_cost"
    if re.search(r"\b(inflation|verdbolg\w*)\b", folded):
        return "cpi"
    if re.search(r"\b(consumer price|cpi|neysluverd\w*|visitala neyslu)\b", folded):
        return "cpi"
    if re.search(r"\b(wage index|launavisit\w*)\b", folded):
        return "wage_index"
    if re.search(r"\b(unemploy\w*|atvinnuleys\w*|atvinnulaus\w*)\b", folded):
        if re.search(r"\b(how many|hve marg|fjoldi|people were|voru atvinnulaus)\b", folded) or re.search(
            r"atvinnulaus", folded
        ) and not re.search(r"atvinnuleys", folded):
            return "unemployment_count"
        if re.search(r"\b(how many|hve marg)\b", folded) and re.search(r"atvinnulaus", folded):
            return "unemployment_count"
        if re.search(r"\b(rate|hlutfall|percent|prosent)\b", folded) or re.search(r"atvinnuleys", folded):
            if re.search(r"\b(how many people were unemployed|hve marg\w* voru atvinnulaus)\b", folded):
                return "unemployment_count"
            return "unemployment_rate"
        return "unemployment_count" if re.search(r"\b(how many|hve marg)\b", folded) else "unemployment_rate"
    if re.search(r"\b(gross domestic|gdp|landsframleid\w*|verg landsframleid\w*|thjodarframleid\w*)\b", folded):
        return "gdp"
    if re.search(r"\b(exports? of goods and services|utflutning\w* voru og|utflutningur voru og thjonustu|utflutning\w* voru og thjonustu)\b", folded) or (
        re.search(r"\b(export|utflutning)\b", folded) and re.search(r"\b(services|thjonust)\b", folded)
    ):
        return "exports_gs"
    if re.search(r"\b(exports? of goods|voruutflutning\w*|export of goods)\b", folded) or (
        re.search(r"\b(export|utflutning)\b", folded) and re.search(r"\b(goods|voru)\b", folded) and "thjonust" not in folded and "service" not in folded
    ):
        return "exports_goods"
    if re.search(r"\b(imports? of goods and services|innflutning\w*)\b", folded) and (
        "thjonust" in folded or "service" in folded or "goods and services" in folded
    ):
        return "imports_gs"
    if re.search(r"\b(imports? of goods and services|innflutningur voru og thjonustu)\b", folded):
        return "imports_gs"
    if re.search(r"\binnflutning\w*\b", folded) and re.search(r"thjonust|service", folded):
        return "imports_gs"
    if re.search(r"\b(arrivals?|gestakom\w*)\b", folded):
        return "arrivals"
    if re.search(r"\b(overnight|gistinaet\w*|gistinat\w*)\b", folded):
        return "overnight"
    if re.search(r"\b(born|births?|babies|children were born|faedd\w*|born)\b", folded) and re.search(
        r"\b(born|birth|faedd|babies|children|born|borN)\b", folded
    ):
        return "births"
    if re.search(r"\b(faedd|born|birth)\b", folded):
        return "births"
    if re.search(r"\b(net immigration|netto adflutning\w*|netto)\b", folded):
        return "net_migration"
    if re.search(r"\b(immigrated|immigration to|fluttu til|flutti til)\b", folded):
        return "immigration_flow"
    if frame.origin == "immigrant" or re.search(r"\b(immigrants?|innflytjend\w*)\b", folded):
        if re.search(r"\b(lived|live|bjuggu|bua|on 1|januar)\b", folded) or frame.origin:
            return "immigrant_stock"
    if re.search(
        r"\b(population|mannfjold\w*|inhabitants|people|lived|live|lives|bjuggu|bua|ibu\w*|folk|how many\w*|hve marg\w*|hvad eru marg\w*|hvad byr\w*|hvad byr)\b",
        folded,
    ):
        return "population"
    if frame.municipality or frame.region:
        return "population"
    return ""


def _subject(frame: QuestionFrame) -> str:
    if frame.municipality:
        return frame.municipality
    if frame.region:
        return frame.region
    if frame.measure:
        return frame.measure
    return ""


def _opinion(folded: str) -> bool:
    if re.search(r"\b(too high|too low|of ha|of lag|of hatt)\b", folded):
        return True
    if re.match(r"\b(is|er|are)\b", folded) and not re.search(r"\b(what|hvad|hver|hve|how)\b", folded):
        return True
    return False


def _weather(folded: str) -> bool:
    return bool(re.search(r"\b(temperature|hitastig\w*|weather|vedur\w*|vedrid\w*)\b", folded))


def _mars(folded: str) -> bool:
    # "mars 2024" is the month. The planet, and the Moon, are not a table.
    if re.search(r"\bmars\s+(?:19|20)\d{2}\b", folded):
        return False
    return bool(re.search(r"\b(on mars|a mars|on the moon|the moon|a tunglinu|a tungli|tunglid)\b", folded))


def _future(folded: str) -> bool:
    return bool(re.search(r"\b(will|verdur|forecast|projection|spa)\b", folded))


def _leftovers(folded: str, frame: QuestionFrame) -> list[str]:
    consumed = set(_STOP)
    consumed.update(_FEMALE)
    consumed.update(_MALE)
    for _name, phrases in _REGIONS:
        for phrase in phrases:
            consumed.update(phrase.split())
    for word in (
        "consumer", "price", "cpi", "wage", "gross", "domestic", "product", "gdp",
        "unemployment", "overnight", "stays", "stay", "registered", "accommodation",
        "building", "cost", "exports", "export", "imports", "import", "goods",
        "services", "service", "arrivals", "arrival", "births", "birth", "born",
        "children", "babies", "immigrants", "immigrant", "immigration", "net",
        "foreign", "visitors", "visitor", "inflation", "share", "population",
        "neysluverds", "launavisitalan", "landsframleidsla", "landsframleidslunni",
        "gistinaetur", "gistinaetur", "byggingarvisitolunnar", "byggingarvisitala",
        "utflutningur", "innflutningur", "voruutflutningur", "gestakomur",
        "innflytjendur", "adflutningur", "atvinnuleysi", "atvinnulausir",
        "mannfjoldinn", "mannfjolda", "landsframleidslan", "verg", "thjonustu",
        "voru", "gesta", "erlendra", "skradum", "gististodum", "gististada",
        "arsmedal", "arsmedaltal", "arsbreyting", "visitolu", "neysluverds",
        "born", "born", "bua", "ibu", "ibuar", "folk", "live", "lived",
    ):
        consumed.add(fold(word))
    if frame.municipality:
        consumed.update(re.findall(r"[a-z0-9]+", fold(frame.municipality)))
        consumed.update(re.findall(r"[a-z0-9]+", fold(frame.municipality_surface)))
    leftovers = []
    for token in re.findall(r"[a-z0-9]+", folded):
        if len(token) < 5 or token.isdigit() or token in consumed:
            continue
        if any(token.startswith(word) or word.startswith(token) for word in consumed if len(word) >= 6):
            continue
        leftovers.append(token)
    return leftovers


def _usable(frame: QuestionFrame) -> bool:
    if frame.blocked or frame.unresolved_place:
        return False
    if not frame.measure:
        return False
    if frame.measure == "trade_balance":
        return False
    # A share, a difference and a sum need two cells. A question that names
    # two measures needs two cards. The existing planner already does both.
    if frame.operation in {"share", "difference", "sum"}:
        return False
    if _compound_measures(fold(frame.corrected or frame.text)):
        return False
    if _ambiguous_period_grain(frame, fold(frame.corrected or frame.text)):
        return False
    # A bare year of unemployment is two published series with the same rate.
    # The quarterly question names one of them. The year does not.
    if frame.measure in {"unemployment_rate", "unemployment_count"} and not (
        frame.period.quarter or frame.period.month
    ):
        return False
    # A year is already named and no place or sex is. The existing binder
    # picks the national series. Preferring the key-figures table cites a
    # different table for the same headcount.
    if (
        frame.measure == "population"
        and frame.period.year
        and not frame.period.implicit
        and not frame.sex
        and not frame.age_exact
        and not frame.municipality
        and not frame.region
        and not frame.origin
    ):
        return False
    if frame.leftovers:
        return False
    return True


def _change_denied(folded: str) -> bool:
    """The change words are there to exclude the change column."""
    return bool(re.search(
        r"\b(not|ekki|rather than|instead of)\b.{0,48}\b(annual change|arsbreyting|the change)\b"
        r"|"
        r"\b(index level|the level)\b.{0,40}\bnot\b",
        folded,
    ))


def _capital_area(folded: str) -> bool:
    """'Capital area' is not the capital region and not Reykjavík."""
    if "capital region" in folded or "hofudborgarsvaed" in folded:
        return False
    return "capital area" in folded


def _bare_age_span(folded: str, frame: QuestionFrame) -> bool:
    """A headcount of an open age band is not one cell.

    A published rate that is itself defined for '25 and older' is a cell.
    """
    if not frame.age_open:
        return False
    if re.search(r"percent|prosent|hlutfall|hlutdeild|\brate\b|visit|index", folded):
        return False
    return bool(re.search(
        r"how many|hve marg|hversu marg|hvad eru marg|people|person|mannfjold|ibu",
        folded,
    ))


def _compound_measures(folded: str) -> bool:
    patterns = (
        r"\b(consumer price|\bcpi\b|neysluverd\w*|visitala neyslu|inflation|verdbolg\w*)\b",
        r"\b(wage index|launavisit\w*)\b",
        r"\b(gross domestic|\bgdp\b|landsframleid\w*)\b",
        r"\b(unemploy\w*|atvinnuleys\w*)\b",
        r"\b(overnight|gistinaet\w*)\b",
        r"\b(births?\b|faedd\w*|\bborn\b)\b",
        r"\b(building cost|byggingarvisit\w*)\b",
        r"\b(population|mannfjold\w*)\b",
    )
    return sum(1 for pattern in patterns if re.search(pattern, folded)) >= 2


def _ambiguous_period_grain(frame: QuestionFrame, folded: str) -> bool:
    """A monthly index named only by a year is an average or one of twelve months."""
    if frame.measure not in {"cpi", "wage_index"}:
        return False
    if frame.operation == "change":
        return False
    if frame.period.month or frame.period.quarter:
        return False
    if frame.period.kind in {"latest", "relative", "range"}:
        return False
    if not frame.period.year:
        return False
    if re.search(r"annual average|arsmedal", folded):
        return False
    return True


def _pipeline(frame: QuestionFrame, expanded: str) -> str:
    """Correct the wording. Do not append measure words.

    Extra words change the subject check: a leader title that contains them
    and a chosen title that does not is withheld, including questions the
    catalogue already answered.
    """
    text = expanded
    if frame.language == "is" and frame.municipality and frame.municipality_surface:
        if fold(frame.municipality_surface) != fold(frame.municipality):
            text = re.sub(re.escape(frame.municipality_surface), frame.municipality, text, count=1)
    if frame.measure == "cpi" and frame.operation == "change":
        folded = fold(text)
        if "change" not in folded and "breyting" not in folded and re.search(r"inflation|verdbolg", folded):
            if frame.language == "is":
                text = "Hver var ársbreyting vísitölu neysluverðs"
            else:
                text = "What was the annual change in the consumer price index"
            if frame.period.month and frame.period.year:
                month = _MONTH_NAME_IS[frame.period.month] if frame.language == "is" else _MONTH_NAME_EN[frame.period.month]
                text = f"{text} í {month} {frame.period.year}" if frame.language == "is" else f"{text} in {month} {frame.period.year}"
            elif frame.period.implicit:
                text = f"{text} núna" if frame.language == "is" else f"{text} now"
    return text


def _result_period(result: dict) -> str:
    for claim in result.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cell in claim.get("cells") or []:
            if isinstance(cell, dict) and cell.get("period"):
                return str(cell["period"])
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    for cell in source.get("cells") or []:
        if isinstance(cell, dict) and cell.get("period"):
            return str(cell["period"])
    return ""


def _covers_year(edition, year: int) -> bool:
    years = set()
    try:
        years = set(edition.years())
    except Exception:
        years = set()
    if not years:
        return True
    return int(year) in years


def _gdp_line(edition) -> bool:
    for variable in getattr(edition, "variables", []) or []:
        for _code, label in getattr(variable, "values", []) or []:
            text = fold(str(label))
            if "verg landsframleidsla" in text or "gross domestic product" in text:
                return True
    return False


def _edition(table, language: str):
    edition = table.edition(language) if hasattr(table, "edition") else None
    return edition


def _values(variable):
    return [(str(code), str(label)) for code, label in (getattr(variable, "values", []) or [])]


def _has_role(edition, role: str) -> bool:
    for variable in getattr(edition, "variables", []) or []:
        if variable_role(variable) == role:
            return True
    return False


def _wider_geo(edition) -> bool:
    for variable in getattr(edition, "variables", []) or []:
        key = fold(getattr(variable, "text", ""))
        if any(mark in key for mark in ("thettbylis", "byggdakjarn", "hverfi", "localit", "urban nucle", "district")):
            return True
    return False


def _match_total(variable) -> str | None:
    totals = {
        "total", "alls", "samtals", "all", "allt", "heild",
        "males and females", "karlar og konur", "both sexes",
    }
    for code, label in _values(variable):
        if fold(label).strip() in totals:
            return code
    for code, label in _values(variable):
        if fold(label).startswith("total"):
            return code
    return None


def _match_label(variable, needles: tuple[str, ...]) -> str | None:
    best = None
    for code, label in _values(variable):
        folded = fold(label)
        if fold(label).strip() in {"total", "alls", "males and females", "karlar og konur"}:
            continue
        for needle in needles:
            if needle in folded:
                best = code
                break
    return best


def _match_sex(variable, sex: str) -> str | None:
    for code, label in _values(variable):
        plain = fold(label).strip()
        if plain in {"total", "alls", "males and females", "karlar og konur", "both sexes"}:
            continue
        female = any(word in plain for word in ("female", "woman", "women", "konur", "kona", "stulka", "girl"))
        male = any(word in plain for word in ("male", "karl", "dreng", "boy")) or plain in {"men", "man"}
        if "female" in plain or "woman" in plain or "women" in plain:
            male = False
        if sex == "female" and female:
            return code
        if sex == "male" and male and not female:
            return code
    return None


def _match_age(variable, age: str) -> str | None:
    for code, label in _values(variable):
        plain = fold(label).strip()
        if "-" in plain or "–" in plain:
            continue
        if re.search(rf"\b{re.escape(age)}\b", plain) and re.search(r"year|ara|ars|old", plain):
            return code
        if plain == age:
            return code
    return None


def _common_prefix(left: str, right: str) -> int:
    count = 0
    for a, b in zip(left, right):
        if a != b:
            break
        count += 1
    return count


def _place_aliases(name: str) -> list[str]:
    folded = fold(name)
    aliases = [folded]
    if len(folded) >= 7:
        aliases.append(folded[:7])
    if len(folded) >= 8:
        aliases.append(folded[:8])
    return aliases


def _sex_aliases(sex: str) -> list[str]:
    if sex == "female":
        return ["females", "women", "konur", "kona"]
    return ["males", "men", "karlar", "karl"]


def _match_place_variable(variable, place: str) -> str | None:
    target = fold(place)
    best = None
    best_len = 0
    for code, label in _values(variable):
        plain = fold(label)
        if plain.strip() in {"total", "alls"}:
            continue
        shared = _common_prefix(target, plain)
        if shared >= 7 and shared > best_len:
            best = code
            best_len = shared
        elif target[:6] and target[:6] in plain and 6 > best_len:
            best = code
            best_len = 6
    return best


def _match_place(edition, role: str, place: str) -> bool:
    for variable in getattr(edition, "variables", []) or []:
        if variable_role(variable) == role and _match_place_variable(variable, place):
            return True
    return False


def _norm_region(text: str) -> str:
    """Drop an Icelandic case ending so 'Suðurlandi' meets 'Suðurland'.

    'South' stays 'south'. It does not become a prefix of 'Southwest'.
    """
    parts = []
    for word in fold(text).split():
        for ending in ("inu", "unum", "inn", "num", "i", "u"):
            if len(word) - len(ending) >= 8 and word.endswith(ending):
                word = word[: -len(ending)]
                break
        parts.append(word)
    return " ".join(parts)


def _region_same(plain: str, needle: str) -> bool:
    if plain == needle:
        return True
    left, right = _norm_region(plain), _norm_region(needle)
    if left == right:
        return True
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    return len(short) >= 10 and long.startswith(short)


def _match_region_variable(variable, region: str) -> str | None:
    labels = _REGION_LABELS.get(region, ())
    needles = tuple(fold(label) for label in labels)
    for code, label in _values(variable):
        plain = fold(label).strip()
        if plain in {"total", "alls", "allt landid"}:
            continue
        if any(_region_same(plain, needle) for needle in needles):
            return code
    return None


def _match_region(edition, region: str) -> bool:
    for variable in getattr(edition, "variables", []) or []:
        if variable_role(variable) == region and False:
            pass
        if variable_role(variable) == "region" and _match_region_variable(variable, region):
            return True
    return False


def _match_origin(edition) -> bool:
    for variable in getattr(edition, "variables", []) or []:
        if variable_role(variable) == "origin" and _match_label(variable, ("immigrant", "innflytjandi")):
            return True
    return False


def _match_migration(variable, measure: str) -> str | None:
    for code, label in _values(variable):
        plain = fold(label).strip()
        net = "net" in plain or "umfram" in plain or "netto" in plain
        if measure == "net_migration" and net:
            return code
        if measure == "immigration_flow" and not net and plain not in {"emigration", "brottfluttir"} and (
            "immigration" in plain or plain in {"adfluttir", "immigration"} or "adflutt" in plain
        ):
            if "brott" in plain:
                continue
            return code
    return None


def _match_unit(variable, frame: QuestionFrame) -> str | None:
    pairs = _values(variable)

    def find(pred) -> str | None:
        for code, label in pairs:
            if pred(fold(label)):
                return code
        return None

    measure = frame.measure
    if measure == "cpi":
        if frame.operation == "change":
            return find(lambda text: "annual change" in text or "arsbreyting" in text)
        return find(lambda text: text.strip() in {"index", "visitala", "consumer price index"} or text.startswith("visitala neyslu") or text.startswith("consumer price index"))
    if measure == "wage_index":
        if frame.operation == "change":
            return find(lambda text: "annual change" in text or "arsbreyting" in text)
        return find(lambda text: "value of index" in text or "visitolugildi" in text or text.strip() in {"index", "visitala"})
    if measure == "building_cost":
        if frame.operation == "change":
            return find(lambda text: "annual change" in text or "arsbreyting" in text)
        return find(lambda text: "annual average" in text or "arsmedal" in text)
    if measure == "unemployment_count":
        return find(lambda text: ("unemployed" in text or "atvinnulaus" in text) and "rate" not in text and "%" not in text)
    if measure == "unemployment_rate":
        return find(lambda text: "unemployment rate" in text or "atvinnuleysi" in text)
    if measure == "population":
        return find(lambda text: "population 1 january" in text or "mannfjoldi 1" in text)
    if measure == "arrivals":
        return find(lambda text: "arrival" in text or "gestakom" in text)
    if measure == "overnight":
        return find(lambda text: "overnight" in text or "gistinaet" in text)
    return None


def _match_category(variable, frame: QuestionFrame) -> str | None:
    pairs = _values(variable)

    def find(pred) -> str | None:
        for code, label in pairs:
            if pred(fold(label), str(label)):
                return code
        return None

    measure = frame.measure
    if measure == "gdp":
        return find(lambda text, raw: (
            ("gross domestic product" in text or "verg landsframleidsla" in text or text.strip().endswith("landsframleidsla"))
            and "income" not in text and "thjodartekj" not in text and "per capita" not in text
        ))
    if measure == "exports_gs":
        return find(lambda text, raw: "6.1" not in raw and ("exports of goods and services" in text or "utflutningur alls" in text))
    if measure == "exports_goods":
        return find(lambda text, raw: "6.1" in raw and ("vorur" in text or "goods" in text or "fob" in text))
    if measure == "imports_gs":
        return find(lambda text, raw: "7.1" not in raw and ("imports of goods and services" in text or "innflutningur alls" in text))
    if measure == "births":
        return find(lambda text, raw: "live birth" in text or "lifandi faed" in text)
    return None


def value_named_by_frame(value: str) -> bool:
    """True when the active frame asked for this cell label."""
    frame = current_frame()
    if frame is None or not frame.use:
        return False
    plain = fold(value).strip()
    if not plain:
        return False
    for aliases in frame.filters().values():
        for alias in aliases:
            needle = fold(alias)
            if len(needle) < 4:
                continue
            if needle in plain or plain in needle or _common_prefix(needle, plain) >= 7:
                return True
    return False
