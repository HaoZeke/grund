"""The derived-answer cut refuses low scores and leaves a level answer."""

from __future__ import annotations

import os
import unittest

from grund.abstain_rule import abstain_for_disagreement, abstain_for_low_score, abstain_reason
from grund.calibrate import load_model, probability


def _chance(features: dict) -> float:
    return probability(features, load_model())


class AbstainRuleTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("GRUND_ABSTAIN_RULE", None)

    def test_change_below_the_cut_is_refused(self) -> None:
        features = {
            "margin": 0.0,
            "rerank": 0.0,
            "measure": 1.0,
            "period": 1.0,
            "agreement": 0.3333333333333333,
        }
        self.assertLess(_chance(features), 0.65)
        self.assertTrue(abstain_for_low_score({"operation": "yoy_pct", "features": features}))

    def test_level_below_the_cut_is_kept(self) -> None:
        features = {
            "margin": 0.0,
            "rerank": 0.0,
            "measure": 1.0,
            "period": 1.0,
            "agreement": 0.6666666666666666,
        }
        self.assertLess(_chance(features), 0.65)
        self.assertFalse(abstain_for_low_score({"operation": "level", "features": features}))

    def test_share_above_the_cut_is_kept(self) -> None:
        features = {
            "margin": 0.2,
            "rerank": 5.0,
            "measure": 1.0,
            "period": 1.0,
            "agreement": 1.0,
        }
        self.assertGreater(_chance(features), 0.65)
        self.assertFalse(abstain_for_low_score({"operation": "share", "features": features}))

    def test_the_same_published_figure_on_another_table_is_kept(self) -> None:
        low = {"agreement": 0.333}
        current = {
            "refused": False,
            "value": 394324,
            "value_display": "394,324",
            "table_id": "MAN00000.px",
            "features": low,
            "source": {"other_value": 394324, "other_table": "MAN03250.px"},
        }
        historical = {
            "refused": False,
            "value": 1926,
            "value_display": "1,926",
            "table_id": "SOG01010.px",
            "features": low,
            "source": {"other_value": 1926, "other_table": "MAN03107.px"},
        }
        same_table = {
            "refused": False,
            "value": 139804,
            "value_display": "139,804",
            "table_id": "MAN03270.px",
            "features": {"agreement": 0.667},
            "source": {"other_value": 139804, "other_table": "MAN03270.px"},
        }
        self.assertFalse(abstain_for_disagreement(current))
        self.assertTrue(abstain_for_disagreement(historical))
        ferry = {
            "refused": False,
            "value": 23861,
            "value_display": "23,861",
            "table_id": "SOG03001.px",
            "features": low,
            "source": {
                "other_value": 23861,
                "other_table": "SAM02003.px",
                "closed_historical": True,
            },
        }
        self.assertFalse(abstain_for_disagreement(ferry))
        self.assertTrue(abstain_for_disagreement(same_table))

    def test_disagreement_is_a_separate_policy(self) -> None:
        features = {"margin": 0.2, "rerank": 1.0, "measure": 1.0, "period": 1.0, "agreement": 0.67}
        row = {"operation": "level", "features": features, "refused": False}
        os.environ["GRUND_ABSTAIN_RULE"] = "disagree"
        self.assertEqual(abstain_reason(row), "path disagreement")
        os.environ["GRUND_ABSTAIN_RULE"] = "off"
        self.assertIsNone(abstain_reason(row))


if __name__ == "__main__":
    unittest.main()