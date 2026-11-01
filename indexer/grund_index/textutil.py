"""Token folding shared by the index, the binder, and the eval generator.

Icelandic ð/þ/æ are mapped to ASCII so a query typed without diacritics still
meets a label stored with them. This is not a stemmer.
"""

from __future__ import annotations

import re
import unicodedata

_STOP = {
    "a", "an", "the", "of", "in", "for", "and", "or", "to", "was", "were", "what",
    "which", "how", "many", "is", "are", "be", "by", "from", "on", "at", "that",
    "this", "with", "per", "according", "into", "over", "under", "than", "then",
    "there", "it", "its", "as", "during", "did", "does", "do", "been", "have",
    "has", "had", "not", "no", "about", "between", "across", "into", "out",
    "og", "i", "ad", "er", "var", "voru", "hvad", "hver", "hversu", "fyrir",
    "um", "fra", "til", "med", "sem", "tad", "tetta", "af", "vid", "eftir",
    "milli", "eru", "vid", "einnig", "their", "theirra",
}

# Month names and abbreviations. A value label that is only a month does not
# mean the catalogue is about that word: "mars" is March on a CPI series and
# also the planet. Coverage of these tokens is decided from titles and
# variable names, not from value labels.
MONTH_NAMES = {
    "january", "jan", "januar",
    "february", "feb", "februar",
    "march", "mar", "mars",
    "april", "apr",
    "may", "mai",
    "june", "jun", "juni",
    "july", "jul", "juli",
    "august", "aug", "agust",
    "september", "sep", "sept",
    "october", "oct", "oktober", "okt",
    "november", "nov",
    "december", "dec", "desember", "des",
}

# Query-side expansions. Keys and values are folded tokens.
SYNONYMS = {
    "women": ["females", "female", "konur"],
    "woman": ["females", "female", "konur"],
    "men": ["males", "male", "karlar"],
    "man": ["males", "male", "karlar"],
    "female": ["females", "konur", "women"],
    "females": ["female", "konur", "women"],
    "male": ["males", "karlar", "men"],
    "males": ["male", "karlar", "men"],
    "konur": ["females", "female", "women", "kyn"],
    "karlar": ["males", "male", "men", "kyn"],
    "kona": ["females", "konur"],
    "karl": ["males", "karlar"],
    "prices": ["price"],
    "lived": ["population", "mannfjoldi"],
    "living": ["population", "mannfjoldi"],
    "live": ["population", "mannfjoldi"],
    "lives": ["population", "mannfjoldi"],
    "inhabitants": ["population", "mannfjoldi"],
    "residents": ["population"],
    "moves": ["migration", "flutning", "buferla"],
    "move": ["migration", "flutning", "buferla"],
    "moved": ["migration", "flutning", "buferla"],
    "moving": ["migration", "flutning", "buferla"],
    "migrated": ["migration", "flutning", "buferla", "internal"],
    "internally": ["internal", "migration", "flutning", "buferla"],
    "internal": ["internally", "migration", "buferla"],
    "fluttu": ["migration", "flutning", "buferla", "internal"],
    "flutningur": ["migration", "flutning", "buferla"],
    "buferlum": ["migration", "flutning", "buferla", "internal"],
    "innanlands": ["internal", "migration", "buferla"],
    "migration": ["flutning", "buferla"],
    "ages": ["age", "aldur"],
    "sexes": ["sex", "kyn"],
    "risen": ["annual", "change"],
    "rose": ["annual", "change"],
    "hjaekkad": ["arbreyting", "breyting", "annual", "change"],
    "laekkad": ["arbreyting", "breyting", "annual", "change"],
    "launavisitalan": ["launavisitala", "wage", "index"],
    "launavisitala": ["wage", "index"],
    "gistinaetur": ["overnight", "gistinottum"],
    "cpi": ["consumer", "price", "index", "vnv", "neysluverds"],
    "vnv": ["consumer", "price", "index", "cpi", "neysluverds"],
    "consumer": ["cpi", "vnv", "neysluverds"],
    "average": ["averages", "medal"],
    "averages": ["average", "medal"],
    "breyting": ["change", "arsbreyting", "annual"],
    "arsbreyting": ["breyting", "annual", "change"],
    "arleg": ["annual", "arsbreyting", "breyting"],
    "verdbolga": ["annual", "change", "neysluverds"],
    "kids": ["children", "bornir"],
    "children": ["child", "born"],
    # Inflected forms that are not the word printed on a table title.
    "ibuum": ["ibuar", "mannfjoldi", "population"],
    "ibuar": ["mannfjoldi", "population"],
    "ibua": ["mannfjoldi", "population"],
    "landsmanna": ["mannfjoldi", "population", "island"],
    "landsmenn": ["mannfjoldi", "population"],
    "bjo": ["mannfjoldi", "population"],
    "bjuggu": ["mannfjoldi", "population"],
    "islandi": ["island", "iceland"],
    "gistinottum": ["gistinaetur", "overnight"],
    "gistinatta": ["gistinaetur", "overnight"],
    "gististodum": ["gististada", "gisting", "accommodation"],
    "skradum": ["skradra", "skrad", "skrasett", "registered"],
    "skrad": ["skrasett", "registered", "skradum"],
    "skradar": ["skrad", "skrasett", "registered"],
    "skrasett": ["skrad", "registered"],
    "registered": ["skrad", "skrasett"],
    "arrived": ["arrival", "arrivals"],
    "arrive": ["arrival", "arrivals"],
    "arrivals": ["arrival"],
    "utlendinga": ["utlendingar", "foreigners"],
    "utlendingum": ["utlendingar", "foreigners"],
    "innflytjendum": ["innflytjendur", "innflytjandi", "immigrants"],
    "innflytjendur": ["innflytjandi", "immigrants"],
    "innflytjandi": ["innflytjendur", "immigrants"],
    "employed": ["starfandi", "employment"],
    "employment": ["starfandi", "employed"],
    "starfandi": ["employed", "employment"],
    "unemployed": ["atvinnulaus", "unemployment"],
    "atvinnulaus": ["unemployed", "unemployment"],
}


# Longest first, so "inum" is not left as "um".
_INFLECTION = ("inum", "unum", "anna", "um", "ar", "ir", "ur", "inn", "an", "i", "a")


def edit_distance_at_most(left: str, right: str, limit: int) -> bool:
    """True when the Levenshtein distance is at most `limit`.

    Used for a single spelling difference such as dependency / dependancy.
    The length gap is a lower bound, so distant strings return immediately.
    """
    if left == right:
        return True
    if limit < 0 or abs(len(left) - len(right)) > limit:
        return False
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for index, left_char in enumerate(left, start=1):
        current = [index]
        row_best = index
        for inner, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(previous[inner] + 1, current[inner - 1] + 1, previous[inner - 1] + cost)
            current.append(value)
            if value < row_best:
                row_best = value
        if row_best > limit:
            return False
        previous = current
    return previous[-1] <= limit


def near_token(left: str, right: str) -> bool:
    """A catalogue word and a question word are the same stem or one edit apart.

    A short shared prefix is not enough: atvinnuleysi is not atvinnuþátttaka.
    dependency and dependancy differ by one letter. An Icelandic case ending
    is a short tail on a shared stem.
    """
    if left == right:
        return True
    if len(left) < 5 or len(right) < 5:
        return False
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    extra = longer[len(shorter):]
    if (
        longer.startswith(shorter)
        and shorter
        and len(shorter) >= 5
        and extra in {"a", "i", "u", "n", "r", "s", "ur", "ar", "ir", "um", "inn", "num"}
    ):
        return True
    if abs(len(left) - len(right)) > 2:
        return False
    if min(len(left), len(right)) >= 8 and left[:4] == right[:4]:
        if edit_distance_at_most(left, right, 1):
            return True
    # equivalents / equivalences: a long shared stem and a short different ending.
    if min(len(left), len(right)) >= 10 and left[:8] == right[:8]:
        return edit_distance_at_most(left, right, 2)
    return False


_LEMMA_CACHE: dict[tuple[str, bool], list[str]] = {}
_NEFNIR_READY = False
# Nefnir is an Icelandic tag guesser. An English word such as "residency"
# becomes "residencyr" if it is offered a noun tag. The source text has to
# be Icelandic before that guess runs.
_ICE_CHARS = set("áéíóúýþæöð")
_ICE_WORDS = {
    "ad", "arid", "bjuggu", "eda", "eftir", "eru", "fyrir", "hvad", "hve",
    "hversu", "karla", "karlar", "konur", "kvenna", "med", "sem", "var", "voru",
}
# A few IcePaHC-style tags. Nefnir will not lemmatise without a tag, and
# guessing every tag in the tagset invents stems. These are the ordinary
# noun, adjective, and verb slots a question word can sit in.
_NEFNIR_TAGS = (
    "nven", "nveo", "nveþ", "nvee", "nvfn", "nvfo", "nken", "nkeo", "nkeþ", "nhee",
    "nhen", "nheo", "nheþ", "lkensf", "lvenvf", "lkeovf", "sfg3eþ", "sfg1eþ", "sng",
)


def icelandic_text(text: str) -> bool:
    """True when `text` is Icelandic, so Nefnir may lemmatize its words."""
    raw = text or ""
    if any(ch in raw.lower() for ch in _ICE_CHARS):
        return True
    words = set(re.findall(r"[a-z]+", fold(raw)))
    return len(words & _ICE_WORDS) >= 2


def lemmas(token: str, *, icelandic: bool = False) -> list[str]:
    """Dictionary-shaped forms of one folded token.

    Systematic case endings first. Nefnir, when it imports and the source
    text is Icelandic, adds a lemma for each ordinary tag, and only a lemma
    that is still the same stem is kept. English text does not call it.
    """
    key = (token, icelandic)
    cached = _LEMMA_CACHE.get(key)
    if cached is not None:
        return cached
    found = [token, *inflections(token)]
    if len(token) >= 6 and token[-1] in "iu":
        found.append(token[:-1])
        found.append(token[:-1] + "a")
    # Past tense fækkaði, fjölgaði: strip ði/di and the infinitive remains.
    if token.endswith("adi") and len(token) >= 7:
        found.append(token[:-2])
    if icelandic:
        try:
            from nefnir import init, lemmatize

            global _NEFNIR_READY
            if not _NEFNIR_READY:
                init()
                _NEFNIR_READY = True
            for tag in _NEFNIR_TAGS:
                try:
                    lemma = fold(lemmatize(token, tag))
                except Exception:
                    continue
                same_stem = (
                    len(lemma) >= 4
                    and len(lemma) <= len(token) + 1
                    and (token.startswith(lemma) or near_token(token, lemma))
                )
                if same_stem:
                    found.append(lemma)
        except Exception:
            pass
    kept = []
    for form in found:
        folded = fold(form)
        if len(folded) < 4:
            continue
        if folded not in kept:
            kept.append(folded)
    _LEMMA_CACHE[key] = kept
    return kept


def inflections(token: str) -> list[str]:
    """Dictionary-shaped candidates for one folded Icelandic token.

    Reykjavíkur shares its stem with Reykjavík. Kópavogi is Kópavogur.
    A final n on a long word is the definite article (launavísitalan).
    Nouns in -andi (innflytjandi) inflect as -endur, -endum, -enda.
    """
    found: list[str] = []
    if token.endswith("andi") and len(token) - 4 >= 5:
        stem = token[:-4]
        found.extend([stem + "endur", stem + "endum", stem + "enda", stem + "endi"])
    for suffix in ("endum", "endur", "enda"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 5:
            stem = token[: -len(suffix)]
            found.append(stem + "andi")
            break
    for suffix in _INFLECTION:
        if token.endswith(suffix) and len(token) - len(suffix) >= 5:
            stem = token[: -len(suffix)]
            found.append(stem)
            if suffix in {"i", "a", "um"}:
                found.append(stem + "ur")
                found.append(stem + "ar")
            break
    if len(token) >= 10 and token.endswith("n") and token[-2] in "aeiou":
        found.append(token[:-1])
    return list(dict.fromkeys(found))


def fold(text: str) -> str:
    lowered = text.lower().replace("ð", "d").replace("þ", "th").replace("æ", "ae")
    decomposed = unicodedata.normalize("NFKD", lowered)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped


def tokens(text: str, *, expand: bool = False) -> list[str]:
    found = re.findall(r"[a-z0-9]+", fold(text))
    kept = [tok for tok in found if tok not in _STOP and (len(tok) > 2 or tok.isdigit())]
    if not expand:
        return kept
    extra: list[str] = []
    icelandic = icelandic_text(text)
    for tok in kept:
        forms = [tok, *lemmas(tok, icelandic=icelandic)]
        for form in forms:
            extra.extend(SYNONYMS.get(form, []))
        extra.extend(form for form in forms if form != tok)
    try:
        from grund_index.kang_bridge import expand as kang_expand

        extra.extend(kang_expand(kept + extra))
    except Exception:
        pass
    return kept + [tok for tok in extra if tok not in kept]


def token_set(text: str, *, expand: bool = False) -> set[str]:
    return set(tokens(text, expand=expand))
