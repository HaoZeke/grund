"""Diacritic folding shared by retrieval and value binding.

Icelandic ð/þ/æ are mapped to ASCII so a query typed without diacritics
meets a label stored with them. Other accents are stripped. The mapping is
the same one the catalogue index uses, so a folded token can be compared
with either side.
"""

from __future__ import annotations

import re
import unicodedata

STOP = {
    "a", "an", "the", "of", "in", "for", "and", "or", "to", "was", "were", "what",
    "which", "how", "many", "is", "are", "be", "by", "from", "on", "at", "that",
    "this", "with", "per", "according", "into", "over", "under", "than", "then",
    "there", "it", "its", "as", "during", "did", "does", "do", "been", "have",
    "has", "had", "not", "no", "about", "between", "across", "out", "its",
    "og", "i", "ad", "er", "var", "voru", "hvad", "hver", "hversu", "fyrir",
    "um", "fra", "til", "med", "sem", "thad", "tad", "thetta", "tetta", "af",
    "vid", "eftir", "milli", "eru", "einnig", "their", "theirra", "thess",
    "thegar", "thvi", "ekki", "bara", "mjög", "mjog", "margur", "mikill",
    "hve", "hverjir", "hva", "thessi", "thessu", "thessar", "vera", "verid",
    "will", "would", "can", "could", "should", "into", "over", "than",
}

# Tokens that are real words but too generic to count as a value-label hit.
GENERIC = {
    "year", "years", "ar", "ara", "old", "number", "total", "index", "percent",
    "percentage", "rate", "change", "quarter", "month", "people", "person",
    "iceland", "island", "figure", "figures", "value", "values", "table",
    "hlutfall", "fjoldi", "tala", "tolur", "gildi",
}


def fold(text: str) -> str:
    lowered = text.lower().replace("ð", "d").replace("þ", "th").replace("æ", "ae")
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def words(text: str) -> list[str]:
    """Word pieces that still carry Icelandic letters, for dictionary lookup."""
    return re.findall(r"[0-9A-Za-zÁÉÍÓÚÝÞÆÖÐáéíóúýþæöð]+", text)


def folded_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(text))
