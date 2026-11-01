"""The scorer credits the claimed figure, not every number in the sentence."""

from grund_eval.track3_score import answer_is_right


def test_an_input_printed_beside_the_claim_is_not_the_answer():
    question = {
        "answers": [{"value": 65.3}],
        "parts": [{"table": "FEL02000", "accepted": ["FEL02000"]}],
    }
    text = (
        "In 2022, the share was 97.5 percent. The part is 63.7 of 65.3."
    )
    numbers, tables, correct = answer_is_right(question, text, ["FEL02000.px"], claimed="97.5")
    assert numbers is False
    assert tables is True
    assert correct is False


def test_the_claimed_value_is_enough_for_a_single_gold_number():
    question = {
        "answers": [{"value": 1550}],
        "parts": [{"table": "MAN06201", "accepted": ["MAN06201"]}],
    }
    numbers, tables, correct = answer_is_right(
        question, "In 2020, the figure was 1,550.", ["MAN06201.px"], claimed="1550"
    )
    assert correct is True
