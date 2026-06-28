import unittest

from government_classification import normalize_government_classification, normalize_location_fields


class GovernmentClassificationTests(unittest.TestCase):
    def test_federal_congress_uses_us_jurisdiction(self):
        row = normalize_government_classification(
            {
                "current_office": "US Representative from CA-12",
                "state": "CA",
                "bioguide_id": "X000001",
            }
        )

        self.assertEqual(
            {
                "government_level": "federal",
                "government_branch": "legislative",
                "office_type": "representative",
                "jurisdiction": "US",
            },
            row,
        )

    def test_state_legislator_wins_before_generic_senator_rule(self):
        row = normalize_government_classification(
            {
                "current_office": "State Senator from CA District 7",
                "state": "CA",
                "external_ids": {"openstates": "ocd-person/example"},
            }
        )

        self.assertEqual("state", row["government_level"])
        self.assertEqual("legislative", row["government_branch"])
        self.assertEqual("senator", row["office_type"])
        self.assertEqual("CA", row["jurisdiction"])

    def test_us_district_representative_is_federal_even_with_state_title(self):
        source = {
            "current_office": "State Representative from US District FL-4",
            "state": "US",
            "district": "FL-4",
            "government_level": "State",
            "government_branch": "Legislative",
            "jurisdiction": "US",
        }
        row = normalize_government_classification(source)

        self.assertEqual(
            {
                "government_level": "federal",
                "government_branch": "legislative",
                "office_type": "representative",
                "jurisdiction": "US",
            },
            row,
        )
        self.assertEqual(
            {"state": "FL", "district": "4"},
            normalize_location_fields(source),
        )

    def test_state_representative_with_state_district_stays_state(self):
        source = {
            "current_office": "State Representative from CA-12",
            "state": "CA",
            "district": "12",
        }
        row = normalize_government_classification(source)

        self.assertEqual(
            {
                "government_level": "state",
                "government_branch": "legislative",
                "office_type": "representative",
                "jurisdiction": "CA",
            },
            row,
        )
        self.assertEqual(
            {"state": "CA", "district": "12"},
            normalize_location_fields(source),
        )

    def test_lowercase_us_district_is_normalized_from_district_field(self):
        source = {
            "current_office": "State Representative",
            "state": "US",
            "district": "fl-4",
        }

        self.assertEqual(
            {"state": "FL", "district": "4"},
            normalize_location_fields(source),
        )

    def test_source_values_override_office_fallback(self):
        row = normalize_government_classification(
            {
                "current_office": "Unknown Office",
                "government_level": "State",
                "government_branch": "Executive",
                "office_type": "Attorney General",
                "jurisdiction": "NY",
            }
        )

        self.assertEqual(
            {
                "government_level": "state",
                "government_branch": "executive",
                "office_type": "attorney_general",
                "jurisdiction": "NY",
            },
            row,
        )

    def test_source_jurisdiction_is_uppercase(self):
        row = normalize_government_classification(
            {
                "current_office": "Unknown Office",
                "government_level": "State",
                "jurisdiction": " ca ",
            }
        )

        self.assertEqual("CA", row["jurisdiction"])


if __name__ == "__main__":
    unittest.main()
