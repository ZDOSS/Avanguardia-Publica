import unittest

from extractors.openstates import _classification


class OpenStatesClassificationTests(unittest.TestCase):
    def test_unknown_role_type_leaves_branch_for_normalizer_fallback(self):
        row = _classification({"type": "attorney_general"}, "ca")

        self.assertEqual("state", row["government_level"])
        self.assertIsNone(row["government_branch"])
        self.assertIsNone(row["office_type"])
        self.assertEqual("CA", row["jurisdiction"])


if __name__ == "__main__":
    unittest.main()
