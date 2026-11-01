"""GRUND_URBAN_AGE refuses one table and states nothing."""

import os
import unittest

from grund.urban_age import refuse_reason


class UrbanAgeTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("GRUND_URBAN_AGE", None)

    def test_off_by_default(self):
        os.environ.pop("GRUND_URBAN_AGE", None)
        result = {"value": "5341", "table_id": "MAN03280", "source": {"title": "Population by degree of urbanisation"}}
        self.assertIsNone(refuse_reason("Hversu margir 40 ára bjuggu á Íslandi 1. janúar 2026?", result))

    def test_refuses_national_year_from_the_split(self):
        os.environ["GRUND_URBAN_AGE"] = "1"
        result = {"value": "5341", "table_id": "MAN03280", "source": {"title": "Population by degree of urbanisation, sex and age"}}
        reason = refuse_reason("Hversu margir 40 ára bjuggu á Íslandi 1. janúar 2026?", result)
        self.assertEqual(reason, "urbanisation split is not the national age count")

    def test_keeps_the_overview_table(self):
        os.environ["GRUND_URBAN_AGE"] = "1"
        result = {"value": "5341", "table_id": "MAN00101", "source": {"title": "Population by sex and age 1841-2026"}}
        self.assertIsNone(refuse_reason("Hversu margir 40 ára bjuggu á Íslandi 1. janúar 2026?", result))

    def test_keeps_an_asked_urbanisation_split(self):
        os.environ["GRUND_URBAN_AGE"] = "1"
        result = {"value": "100", "table_id": "MAN03280", "source": {"title": "Population by degree of urbanisation"}}
        self.assertIsNone(refuse_reason("Hve margir 40 ára bjuggu á þéttbýlisstigi 1?", result))


if __name__ == "__main__":
    unittest.main()
