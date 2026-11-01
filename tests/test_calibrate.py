import json
from pathlib import Path

from grund.calibrate import apply_threshold, choose_threshold, report_block, trustsql

ROOT = Path(__file__).resolve().parents[1]


def test_threshold_turns_a_wrong_answer_into_an_abstention():
    rows = [
        {
            "id": "right",
            "correct": True,
            "refused": False,
            "expect_refuse": False,
            "features": {"margin": 1, "rerank": 1, "measure": 1, "period": 1, "agreement": 1},
            "cited_table": True,
            "cited_link": True,
        },
        {
            "id": "wrong",
            "correct": False,
            "refused": False,
            "expect_refuse": False,
            "features": {"margin": 0, "rerank": 0, "measure": 0, "period": 0, "agreement": 0},
            "cited_table": True,
            "cited_link": True,
        },
        {
            "id": "gold-refuse",
            "correct": True,
            "refused": True,
            "expect_refuse": True,
            "features": None,
        },
    ]
    model = {
        "features": ["margin", "rerank", "measure", "period", "agreement"],
        "mean": [0, 0, 0, 0, 0],
        "scale": [1, 1, 1, 1, 1],
        "weights": [2, 2, 2, 2, 2],
        "bias": -2,
        "threshold": 0.5,
    }
    applied = apply_threshold(rows, model)
    by_id = {row["id"]: row for row in applied}
    assert by_id["wrong"]["refused"] is True
    assert by_id["right"]["refused"] is False
    block = report_block(applied)
    assert block["trustsql"] == trustsql(
        [
            {"correct": True, "refused": False, "expect_refuse": False},
            {"correct": False, "refused": True, "expect_refuse": False},
            {"correct": True, "refused": True, "expect_refuse": True},
        ]
    )
    assert block["trustsql"] == 2
    assert block["wrong_when_answering"]["wrong"] == 0
    assert block["citation"]["stated_with_table_and_link"] == 1


def test_the_cut_cannot_refuse_the_whole_set():
    """A cut that states nothing can win TrustSQL and still be a bug."""
    rows = []
    for index in range(10):
        rows.append(
            {
                "correct": True,
                "refused": False,
                "expect_refuse": False,
                "features": {"margin": 0.2, "rerank": 0.2, "measure": 1, "period": 1, "agreement": 0.3},
            }
        )
    for index in range(10):
        rows.append(
            {
                "correct": False,
                "refused": False,
                "expect_refuse": False,
                "features": {"margin": 0.0, "rerank": 0.0, "measure": 0, "period": 0, "agreement": 0.0},
            }
        )
    model = {
        "features": ["margin", "rerank", "measure", "period", "agreement"],
        "mean": [0, 0, 0, 0, 0],
        "scale": [1, 1, 1, 1, 1],
        "weights": [1, 1, 1, 1, 1],
        "bias": -1,
        "threshold": 0.99,
    }
    # Refusing every answer scores 0. Stating the ten wrong answers scores -100.
    # The eligible cuts are the ones that still state at least 30%.
    threshold, _score = choose_threshold(rows, model, min_coverage=0.30)
    applied = apply_threshold(rows, model, threshold)
    stated = sum(1 for row in applied if not row.get("refused"))
    assert stated / len(rows) >= 0.30


def test_the_shipped_cut_states_at_least_30_percent_of_dev_a():
    """The default path must not abstain on the whole of dev-A."""
    from grund.abstain_rule import abstain_for_disagreement

    fixture = ROOT / "tests" / "fixtures" / "dev-a-gates.json"
    rows = json.loads(fixture.read_text(encoding="utf-8"))
    assert len(rows) >= 100
    stated = 0
    for row in rows:
        if row.get("refused"):
            continue
        if abstain_for_disagreement(row):
            continue
        stated += 1
    assert stated / len(rows) >= 0.30, f"stated {stated}/{len(rows)}"
