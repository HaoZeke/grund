"""Icelandic and English names for the same statistical concept.

A trigger is a lemma or a phrase. The heads are the words added to the
query so a paraphrase meets the other language's table title. Heads are
ordinary terminology, not table identifiers.
"""

from __future__ import annotations

import os

from grund_lang.fold import STOP, fold
from grund_lang.types import Analysis

# Each concept: triggers (folded tokens), phrases (folded substrings), heads.
_CONCEPTS: dict[str, dict[str, tuple[str, ...]]] = {
    "capital_region": {
        "triggers": ("hofudborgarsvaedi", "hofudborg"),
        "phrases": ("capital region", "capital area", "greater reykjavik", "hofudborgarsvaed"),
        "heads": ("hofudborgarsvaedi", "capital", "region"),
    },
    "population": {
        "triggers": ("mannfjoldi", "ibui", "ibuar", "landsmadur", "landsmenn", "population", "inhabitant", "inhabitants", "resident", "residents", "bua", "live", "lived", "living"),
        "phrases": ("how many people", "mannfjoldi"),
        "heads": ("mannfjoldi", "population", "ibui", "inhabitant"),
    },
    "mean_age": {
        "triggers": ("medalaldur",),
        "phrases": ("mean age", "average age", "medalaldur"),
        "heads": ("medalaldur", "mean", "age"),
    },
    "dependency_ratio": {
        "triggers": ("framfaersluhlutfall", "hadshlutfall"),
        "phrases": ("dependency ratio", "framfaersluhlutfall", "hadshlutfall"),
        "heads": ("framfaersluhlutfall", "dependency", "ratio"),
    },
    "births": {
        "triggers": ("faeding", "faedingar", "faeddur", "faedd", "birth", "births", "born"),
        "phrases": ("children were born", "bornir", "faeddust"),
        "heads": ("faeding", "birth", "born"),
    },
    "deaths": {
        "triggers": ("andlat", "death", "deaths", "died", "mortality", "deyja", "danir", "dani", "letust"),
        "phrases": ("andlat",),
        "heads": ("andlat", "death", "mortality"),
    },
    "migration_internal": {
        "triggers": ("innanlands", "buferlaflutningur", "buferla", "internal", "internally"),
        "phrases": (
            "internal migration", "buferlaflutning", "fluttust innan", "fluttist innan",
            "within the country", "within the municipality", "within a municipality",
            "between regions", "between municipalities", "innanlands",
        ),
        "heads": ("buferlaflutningur", "internal", "migration", "innanlands"),
    },
    "migration_international": {
        "triggers": ("adfluttur", "brottfluttur", "utflutningur"),
        "phrases": (
            "external migration", "international migration", "milli landa",
            "from abroad", "fra utlondum", "til utlanda", "to iceland from",
        ),
        "heads": ("external", "migration", "international"),
    },
    "immigrants": {
        "triggers": ("innflytjandi", "innflytjendur", "immigrant", "immigrants"),
        "phrases": ("innflytjend", "of foreign origin"),
        "heads": ("innflytjandi", "immigrant", "origin", "bakgrunnur"),
    },
    "citizenship_icelandic": {
        "triggers": (),
        "phrases": (
            "icelandic citizen", "icelandic citizenship",
            "islenskir rikisborgar", "islenskt rikisfang", "islenskir borgarar",
        ),
        "heads": ("rikisborgari", "citizen", "icelandic"),
    },
    "citizenship_foreign": {
        "triggers": (),
        "phrases": ("foreign citizen", "foreign citizenship", "erlendir rikisborgarar", "erlent rikisfang", "foreign citizens"),
        "heads": ("rikisborgari", "citizen", "foreign"),
    },
    "unemployment": {
        "triggers": ("atvinnuleysi", "atvinnulaus", "unemployment", "unemployed"),
        "phrases": ("atvinnuleysi", "unemployment"),
        "heads": ("atvinnuleysi", "unemployment"),
    },
    "gdp": {
        "triggers": ("landsframleidsla", "gdp"),
        "phrases": ("gross domestic product", "landsframleidsl", "verg landsframleidsl"),
        "heads": ("landsframleidsla", "gdp", "gross", "domestic", "product"),
    },
    "exchange_rate": {
        "triggers": ("gengi", "gengisvisit", "exchange"),
        "phrases": ("exchange rate", "selling rate", "us dollar", "bandarikjadals", "solugengi", "medalsolugengi"),
        "heads": ("gengi", "exchange", "rate", "dollar", "usd"),
    },
    "cpi": {
        "triggers": ("cpi", "vnv", "neysluverd", "verdbolga", "verdlag"),
        "phrases": ("consumer price", "visitala neysluverds", "neysluverd"),
        "heads": ("neysluverd", "consumer", "price", "visitala"),
    },
    "wage_index": {
        "triggers": ("launavisitala",),
        "phrases": ("wage index", "launavisitala", "visitala launa"),
        "heads": ("launavisitala", "wage", "index"),
    },
    "annual_change": {
        "triggers": ("arsbreyting", "verdbolga"),
        "phrases": ("annual change", "yearly change", "arsbreyting", "arleg breyting", "milli ara"),
        "heads": ("arsbreyting", "change", "annual"),
    },
    "annual_average": {
        "triggers": ("arsmedaltal", "arsmedal"),
        "phrases": ("annual average", "arsmedaltal", "yearly average"),
        "heads": ("arsmedaltal", "annual", "average"),
    },
    "overnight_stays": {
        "triggers": ("gistinaetur", "gistinott", "gistinottum"),
        "phrases": ("overnight stay", "gistinaet", "gistinott"),
        "heads": ("gistinaetur", "overnight", "stay"),
    },
    "accommodation": {
        "triggers": ("gististadur",),
        "phrases": ("registered accommodation", "gististada", "accommodation"),
        "heads": ("gististadur", "accommodation"),
    },
    "household_consumption": {
        "triggers": ("einkaneysla",),
        "phrases": ("household consumption", "einkaneysla", "final consumption", "private consumption"),
        "heads": ("einkaneysla", "consumption", "household"),
    },
    "sex_female": {
        "triggers": ("kona", "konur", "female", "females", "woman", "women", "stulka", "stulkur", "girl", "girls"),
        "phrases": (),
        "heads": ("kona", "female", "females", "kyn", "sex"),
    },
    "sex_male": {
        "triggers": ("karl", "karlar", "male", "males", "man", "men", "drengur", "drengir", "boy", "boys"),
        "phrases": (),
        "heads": ("karl", "male", "males", "kyn", "sex"),
    },
    "ships": {
        "triggers": ("skipakoma", "skipakomur"),
        "phrases": ("ship arrival", "port call", "skipakomur"),
        "heads": ("skipakoma", "ship", "arrival"),
    },
}


def detect_concepts(analysis: Analysis) -> list[str]:
    lemmas = {token.lemma for token in analysis.tokens}
    bag = lemmas | {token.folded for token in analysis.tokens}
    # börn folds to the English word "born". The lemma is barn, so that
    # surface is not a birth.
    if "barn" in lemmas and "born" not in lemmas:
        bag.discard("born")
    text = fold(analysis.text)
    if os.environ.get("GRUND_QUERY_FIX", "1") == "0":
        bag = set(bag)
        bag.discard("verdlag")
    found: list[str] = []
    for name, spec in _CONCEPTS.items():
        if any(trigger in bag for trigger in spec["triggers"]):
            found.append(name)
            continue
        if any(phrase and phrase in text for phrase in spec["phrases"]):
            found.append(name)
    if "unemployment" in found and "employment" in found:
        found = [name for name in found if name != "employment"]
    # "men" must not fire on a question that only said "women", and the
    # reverse. The trigger lists are disjoint tokens, so this is a guard
    # for a lemma that collapsed both.
    # "Vísitalan" with no wage word is the consumption price index.
    # "Launavísitala" keeps its own token, so it does not take this path.
    if (
        os.environ.get("GRUND_QUERY_FIX", "1") != "0"
        and "visitala" in bag
        and "launavisitala" not in bag
        and "laun" not in bag
        and "wage" not in bag
        and "cpi" not in found
    ):
        found.append("cpi")
    if "sex_female" in found and "sex_male" in found:
        if "woman" in bag or "women" in bag or "kona" in bag or "konur" in bag:
            if "man" not in bag and "men" not in bag and "karl" not in bag and "karlar" not in bag:
                found = [name for name in found if name != "sex_male"]
    return found


def expand_terms(analysis: Analysis, terms: list[str]) -> list[str]:
    """Content terms plus the other language's name for each concept found."""
    extra: list[str] = []
    for name in analysis.concepts:
        for head in _CONCEPTS[name]["heads"]:
            if head not in STOP and head not in terms and head not in extra:
                extra.append(head)
    return terms + extra
