"""Baselines the harness scores next to Grund.

naive_bm25 picks the top title match, the latest period, and the first value
of every other variable. It does not parse the question and it does not refuse.

plain_llm asks an OpenAI-compatible model with no tools and no table. It is
skipped when GRUND_LLM_BASE_URL is unset; the harness records that instead of
inventing a score.
"""

from __future__ import annotations

import re

from grund.llm import ChatClient
from grund.validator import ValidationError, query_body, validate
from grund_index.catalogue import Catalogue
from grund_index.client import PxWebClient, PxWebError
from grund_index.textutil import tokens
from grund_rails.numbers import find_numbers


def naive_bm25(catalogue: Catalogue, client: PxWebClient, question: str) -> dict:
    if not catalogue.tables:
        return _refuse("empty index")
    query = tokens(question)
    scores = catalogue.bm25.scores(query)
    index = max(range(len(scores)), key=lambda item: scores[item])
    if scores[index] <= 0:
        return _refuse("no lexical match")
    table = catalogue.tables[index]
    edition = table.edition("en") or table.edition("is")
    if edition is None:
        return _refuse("no edition")
    selections = []
    for variable in edition.variables:
        if not variable.values:
            continue
        code = variable.codes()[-1] if variable.time else variable.codes()[0]
        selections.append({"code": variable.code, "selection": {"filter": "item", "values": [code]}})
    try:
        validate(edition, selections)
        payload = client.post_json(edition.url, query_body(selections))
    except (ValidationError, PxWebError) as exc:
        return _refuse(str(exc))
    data = payload.get("data") or []
    if not data:
        return _refuse("empty response")
    value = data[0]["values"][0]
    key = data[0]["key"]
    return {
        "answer": f"{value}",
        "refused": False,
        "clarify": False,
        "value": value,
        "table_id": table.id,
        "source": {
            "table_id": table.id,
            "api_url": edition.url,
            "retrieved_at": "baseline",
            "cells": [{"key": key, "value": value}],
            "preliminary": False,
        },
    }


def plain_llm(chat: ChatClient, question: str) -> dict | None:
    if not chat.settings.enabled():
        return None
    text = chat.complete(
        [
            {
                "role": "system",
                "content": (
                    "Answer the statistics question from memory in one sentence. "
                    "Include a number. Do not mention that you are unsure."
                ),
            },
            {"role": "user", "content": question},
        ],
        temperature=0,
    )
    numbers = find_numbers(text, "en") + find_numbers(text, "is")
    return {
        "answer": text,
        "refused": False,
        "clarify": False,
        "value": str(numbers[0]) if numbers else None,
        "table_id": None,
        "source": None,
    }


def _refuse(detail: str) -> dict:
    return {
        "answer": detail,
        "refused": True,
        "clarify": False,
        "value": None,
        "table_id": None,
        "source": None,
    }
