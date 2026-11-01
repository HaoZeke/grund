"""A short question still has to share a word with the cited title."""

from grund_rails.cell_claim import covers_question


def _claim(title: str):
    return [{"cells": [{"title": title, "labels": {}, "period": "2000"}]}]


def test_volumes_published_does_not_cover_a_school_table():
    question = "Hve mörg bindi voru gefin út alls árið 2000?"
    assert covers_question(question, _claim("Brottfall starfsfólks við kennslu í grunnskólum")) is False


def test_a_question_with_no_content_word_is_left_to_the_other_checks():
    assert covers_question("By how much did Oil use fall from 2019 to 2020?", _claim("Oil use")) is True
