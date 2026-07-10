import unittest

from extractors.financial_disclosures import lookup_disclosures
from source_health import SourceHealthTracker


def _filing(doc_id, *, filer="alex public", state="CA", district="4"):
    return {
        "doc_id": doc_id,
        "filing_type": "Annual Financial Disclosure",
        "filing_date": "2026-05-01",
        "doc_url": f"https://example.test/{doc_id}.pdf",
        "year": "2026",
        "_filer_name": filer,
        "_state": state,
        "_district": district,
    }


class FinancialDisclosureIdentityTests(unittest.TestCase):
    def test_state_and_district_disambiguate_and_private_context_is_stripped(self):
        index = {
            "alex public": [
                _filing("ca-4"),
                _filing("ny-2", state="NY", district="2"),
            ]
        }

        rows = lookup_disclosures(index, ["Alex Public"], state="CA", district="4")

        self.assertEqual(["ca-4"], [row["doc_id"] for row in rows])
        self.assertFalse(any(key.startswith("_") for key in rows[0]))

    def test_expected_context_never_accepts_name_only_filing(self):
        health = SourceHealthTracker("house")
        index = {"alex public": [_filing("missing", state=None, district=None)]}

        rows = lookup_disclosures(
            index,
            ["Alex Public"],
            state="CA",
            district="4",
            health=health,
        )

        self.assertEqual([], rows)
        self.assertEqual(1, health.skip_reasons["missing_state_identity_context"])

    def test_multiple_filer_identities_with_same_name_are_rejected(self):
        index = {
            "alex public": [
                _filing("one", filer="alex public", state=None, district=None),
                _filing("two", filer="alex q public", state=None, district=None),
            ]
        }

        self.assertEqual([], lookup_disclosures(index, ["Alex Public"]))


if __name__ == "__main__":
    unittest.main()
