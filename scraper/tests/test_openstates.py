import unittest

from extractors.openstates import _classification, _map_person, _state_from_path


class OpenStatesClassificationTests(unittest.TestCase):
    def test_unknown_role_type_leaves_branch_for_normalizer_fallback(self):
        row = _classification({"type": "attorney_general"}, "ca")

        self.assertEqual("state", row["government_level"])
        self.assertIsNone(row["government_branch"])
        self.assertIsNone(row["office_type"])
        self.assertEqual("CA", row["jurisdiction"])

    def test_state_from_path_extracts_dataset_code(self):
        state = _state_from_path("people-main/data/az/legislature/Jane-Public.yml")

        self.assertEqual("az", state)

    def test_map_person_keeps_state_legislator(self):
        row = _map_person(
            {
                "id": "ocd-person/state-person",
                "name": "Jane Public",
                "roles": [{"type": "lower", "district": "3"}],
                "party": [{"name": "Independent"}],
            },
            "az",
        )

        self.assertIsNotNone(row)
        self.assertEqual("Jane Public", row["full_name"])
        self.assertEqual("State Representative from AZ District 3", row["current_office"])
        self.assertEqual("AZ", row["state"])
        self.assertEqual("state", row["government_level"])
        self.assertEqual("AZ", row["jurisdiction"])
        self.assertEqual("ocd-person/state-person", row["external_ids"]["openstates"])

    def test_map_person_skips_federal_openstates_dataset(self):
        row = _map_person(
            {
                "id": "ocd-person/federal-person",
                "name": "Yassamin Ansari",
                "roles": [{"type": "lower", "district": "AZ-3"}],
                "party": [{"name": "Democratic"}],
            },
            "us",
        )

        self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
