import unittest

from canonical_identity_rules import (
    deterministic_identity_keys,
    group_profiles_by_deterministic_identity,
    same_name_review_candidates,
)


class CanonicalIdentityRuleTests(unittest.TestCase):
    def test_same_name_without_deterministic_identity_does_not_merge(self):
        rows = [
            {"id": "legacy-a", "full_name": "Alex Lee", "external_ids": {}},
            {"id": "legacy-b", "full_name": "Alex   Lee", "external_ids": {}},
        ]

        groups = group_profiles_by_deterministic_identity(rows)
        candidates = same_name_review_candidates(rows, groups)

        self.assertNotEqual(groups["legacy-a"], groups["legacy-b"])
        self.assertEqual(
            [
                {
                    "candidate_type": "same_name_review",
                    "source_legacy_politician_id": "legacy-a",
                    "candidate_legacy_politician_id": "legacy-b",
                    "normalized_name": "alex lee",
                }
            ],
            candidates,
        )

    def test_shared_bioguide_merges_even_when_names_drift(self):
        rows = [
            {"id": "legacy-a", "full_name": "Jane Q. Public", "bioguide_id": "P000001"},
            {"id": "legacy-b", "full_name": "Jane Public", "bioguide_id": "P000001"},
        ]

        groups = group_profiles_by_deterministic_identity(rows)

        self.assertEqual(groups["legacy-a"], groups["legacy-b"])

    def test_shared_trusted_external_id_merges(self):
        rows = [
            {
                "id": "legacy-a",
                "full_name": "Casey Rivera",
                "external_ids": {"fec": ["H0CA00001", "S0CA00001"]},
            },
            {
                "id": "legacy-b",
                "full_name": "Casey M. Rivera",
                "external_ids": {"fec": ["H0CA00001"]},
            },
        ]

        groups = group_profiles_by_deterministic_identity(rows)

        self.assertEqual(groups["legacy-a"], groups["legacy-b"])

    def test_same_name_with_conflicting_deterministic_ids_is_review_blocked(self):
        rows = [
            {"id": "legacy-a", "full_name": "Jordan Smith", "bioguide_id": "S000001"},
            {"id": "legacy-b", "full_name": "Jordan Smith", "bioguide_id": "S000002"},
        ]

        groups = group_profiles_by_deterministic_identity(rows)
        candidates = same_name_review_candidates(rows, groups)

        self.assertNotEqual(groups["legacy-a"], groups["legacy-b"])
        self.assertEqual("same_name_conflicting_deterministic_ids", candidates[0]["candidate_type"])

    def test_name_party_and_office_are_not_deterministic_keys(self):
        row = {
            "id": "legacy-a",
            "full_name": "Taylor Morgan",
            "party": "Independent",
            "current_office": "Mayor",
            "external_ids": {},
        }

        self.assertEqual((), deterministic_identity_keys(row))


if __name__ == "__main__":
    unittest.main()
