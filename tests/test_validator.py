import pytest

from grund.validator import ValidationError, validate
from grund_index.model import Edition, Variable


def edition() -> Edition:
    return Edition(
        lang="en",
        title="Example",
        db="Efnahagur",
        path=["Efnahagur"],
        path_texts=["Economy"],
        url="https://example.test/T.px",
        updated=None,
        variables=[
            Variable("Year", "Year", True, False, [("2023", "2023"), ("2024", "2024")]),
            Variable("Sex", "Sex", False, False, [("Total", "Total"), ("1", "Males"), ("2", "Females")]),
        ],
    )


def test_accepts_a_query_that_uses_real_codes():
    validate(
        edition(),
        [
            {"code": "Year", "selection": {"filter": "item", "values": ["2024"]}},
            {"code": "Sex", "selection": {"filter": "item", "values": ["2"]}},
        ],
    )


def test_rejects_unknown_codes_and_missing_variables():
    with pytest.raises(ValidationError) as caught:
        validate(
            edition(),
            [{"code": "Year", "selection": {"filter": "item", "values": ["2099"]}}],
        )
    message = str(caught.value)
    assert "2099" in message
    assert "Sex" in message


def test_rejects_duplicate_variables_and_top_filter_shape():
    with pytest.raises(ValidationError):
        validate(
            edition(),
            [
                {"code": "Year", "selection": {"filter": "item", "values": ["2024"]}},
                {"code": "Year", "selection": {"filter": "item", "values": ["2023"]}},
                {"code": "Sex", "selection": {"filter": "top", "values": ["nope"]}},
            ],
        )


def test_top_filter_is_legal_when_the_count_fits():
    validate(
        edition(),
        [
            {"code": "Year", "selection": {"filter": "top", "values": ["1"]}},
            {"code": "Sex", "selection": {"filter": "item", "values": ["Total"]}},
        ],
    )
