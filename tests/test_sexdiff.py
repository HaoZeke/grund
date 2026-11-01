"""Sex-difference detection. The flag is off unless the test turns it on."""

from __future__ import annotations

import os

from grund.sexdiff import formula_for, is_sex_difference, operand_order


def test_flag_off_is_not_the_family():
    os.environ.pop("GRUND_SEXDIFF", None)
    question = "Hversu miklu munaði á fjölda karla og kvenna á Íslandi árið 2020?"
    assert is_sex_difference(question) is False


def test_gap_family_on():
    os.environ["GRUND_SEXDIFF"] = "1"
    try:
        assert is_sex_difference("Hversu miklu munaði á fjölda karla og kvenna á Íslandi árið 2020?")
        assert is_sex_difference("How many more men than women lived in Iceland on 1 January 2026?")
        assert is_sex_difference("Hve mörgum fleiri karlar en konur bjuggu á Íslandi 1. janúar 2026?")
        assert not is_sex_difference("Hversu hátt hlutfall íbúa voru karlar árið 2018?")
        assert not is_sex_difference("Hversu margir karlar bjuggu á Íslandi árið 2020?")
        assert not is_sex_difference("Hvert var atvinnuleysi kvenna á öðrum ársfjórðungi 2026?")
    finally:
        os.environ.pop("GRUND_SEXDIFF", None)


def test_operand_order_follows_the_question():
    os.environ["GRUND_SEXDIFF"] = "1"
    try:
        assert operand_order("How many more women than men lived in Hafnarfjörður in 2011?") == ("f", "m")
        assert operand_order("How many more men than women lived in Iceland in 1990?") == ("m", "f")
        assert operand_order("Hve mörgum fleiri konur en karlar bjuggu í Hafnarfirði árið 2011?") == ("f", "m")
        assert operand_order("women minus men") == ("f", "m")
        assert operand_order("men minus women") == ("m", "f")
        assert operand_order("konur minus karlar") == ("f", "m")
        assert operand_order("Hversu miklu munaði á fjölda karla og kvenna á Íslandi árið 2020?") == ("m", "f")
        assert formula_for("How many more women than men lived in Iceland in 2011?") == "women - men"
        assert formula_for("men minus women in Iceland") == "men - women"
    finally:
        os.environ.pop("GRUND_SEXDIFF", None)
