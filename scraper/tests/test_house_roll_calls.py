import unittest
from datetime import date
from unittest.mock import patch

from extractors import house_roll_calls
from source_health import SourceHealthTracker


def _listing(*vote_numbers: int, year: int = 2026) -> str:
    return "\n".join(
        f'<a data-action="/Votes/{year}{vote_number}">{vote_number}</a>'
        for vote_number in vote_numbers
    )


def _roll_call_xml(vote_number: int, first_vote: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rollcall-vote>
  <vote-metadata>
    <congress>119</congress>
    <session>2nd</session>
    <rollcall-num>{vote_number}</rollcall-num>
    <action-date>14-Jul-2026</action-date>
    <vote-question>On Passage</vote-question>
  </vote-metadata>
  <vote-data>
    <recorded-vote><legislator name-id="A000001">Alpha</legislator><vote>{first_vote}</vote></recorded-vote>
    <recorded-vote><legislator name-id="B000002">Bravo</legislator><vote>Nay</vote></recorded-vote>
    <recorded-vote><legislator name-id="Z000999">Former Member</legislator><vote>Present</vote></recorded-vote>
    <recorded-vote><legislator>Missing ID</legislator><vote>Not Voting</vote></recorded-vote>
  </vote-data>
</rollcall-vote>"""


class _Response:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class HouseRollCallShadowTests(unittest.TestCase):
    def test_current_congress_session_handles_the_january_transition(self):
        self.assertEqual(
            (119, 1, 2025),
            house_roll_calls._current_congress_session(date(2026, 1, 2)),
        )
        self.assertEqual(
            (119, 2, 2026),
            house_roll_calls._current_congress_session(date(2026, 7, 14)),
        )
        self.assertEqual(
            (119, 2, 2026),
            house_roll_calls._current_congress_session(date(2027, 1, 2)),
        )

    def test_listing_parser_keeps_only_expected_year_and_unique_vote_numbers(self):
        listing = "\n".join(
            (
                _listing(240, 239, 240),
                _listing(301, year=2025),
            )
        )

        self.assertEqual(
            [(2026, 240), (2026, 239)],
            house_roll_calls._parse_member_votes_page(listing, 2026),
        )

    def test_listing_parser_rejects_unrecognized_nonempty_markup(self):
        with self.assertRaises(ValueError):
            house_roll_calls._parse_member_votes_page(
                "<main>Unexpected page</main>", 2026
            )

    def test_listing_parser_allows_an_empty_official_result_set(self):
        self.assertEqual(
            [],
            house_roll_calls._parse_member_votes_page(
                "<div>0 Results</div>", 2026
            ),
        )

    def test_member_votes_url_uses_the_official_session_suffix(self):
        self.assertIn(
            "CongressNum=119&Session=1st",
            house_roll_calls._member_votes_url(119, 1, 1),
        )
        self.assertIn(
            "CongressNum=119&Session=2nd",
            house_roll_calls._member_votes_url(119, 2, 1),
        )

    def test_shadow_fetches_bounded_window_and_compares_only_bioguide_ids(self):
        health = SourceHealthTracker("house_roll_call_shadow", min_attempts_for_rate=3)
        govtrack_votes = {
            "A000001": {
                "house:119:2026:2": "Aye",
                "house:119:2026:1": "Yea",
            },
            "B000002": {"house:119:2026:2": "Nay"},
        }

        with patch(
            "extractors.house_roll_calls.requests.get",
            side_effect=[
                _Response(text=_listing(2, 1)),
                _Response(text=_roll_call_xml(2, "Yea")),
                _Response(text=_roll_call_xml(1, "Nay")),
            ],
        ) as mock_get:
            report = house_roll_calls.get_recent_house_roll_call_shadow(
                {"A000001", "B000002"},
                govtrack_votes,
                limit=2,
                health=health,
                today=date(2026, 7, 14),
            )

        self.assertEqual(3, mock_get.call_count)
        self.assertEqual("healthy", health.status)
        self.assertEqual(3, health.attempts)
        self.assertEqual(3, health.successes)
        self.assertEqual(2, report.roll_calls_listed)
        self.assertEqual(2, report.roll_calls_fetched)
        self.assertEqual(8, report.member_votes_seen)
        self.assertEqual(2, report.member_votes_missing_bioguide_id)
        self.assertEqual(4, report.exact_bioguide_matches)
        self.assertEqual({"Z000999"}, report.unmatched_bioguide_ids)
        self.assertEqual(2, report.govtrack_vote_cast_matches)
        self.assertEqual(1, report.govtrack_vote_cast_mismatches)
        self.assertEqual(1, report.govtrack_vote_not_observed)
        self.assertEqual(
            1,
            report.counters()["house_roll_call_shadow_unmatched_bioguide_ids"],
        )

    def test_shadow_pages_the_public_listing_to_reach_its_bounded_window(self):
        page_one = _listing(*range(11, 1, -1))
        page_two = _listing(1)

        def response_for(url, **_kwargs):
            if "MemberVotes?Page=1" in url:
                return _Response(text=page_one)
            if "MemberVotes?Page=2" in url:
                return _Response(text=page_two)
            vote_number = int(url.rsplit("roll", maxsplit=1)[1].split(".", maxsplit=1)[0])
            return _Response(text=_roll_call_xml(vote_number, "Yea"))

        with patch(
            "extractors.house_roll_calls.requests.get",
            side_effect=response_for,
        ) as mock_get:
            report = house_roll_calls.get_recent_house_roll_call_shadow(
                {"A000001", "B000002"},
                {},
                limit=11,
                today=date(2026, 7, 14),
            )

        self.assertEqual(13, mock_get.call_count)
        self.assertEqual(11, report.roll_calls_listed)
        self.assertEqual(11, report.roll_calls_fetched)

    def test_shadow_returns_early_without_bioguide_join_keys(self):
        health = SourceHealthTracker("house_roll_call_shadow", min_attempts_for_rate=3)
        with patch("extractors.house_roll_calls.requests.get") as mock_get:
            report = house_roll_calls.get_recent_house_roll_call_shadow(
                {"", "  "},
                {},
                health=health,
                today=date(2026, 7, 14),
            )

        self.assertEqual(0, mock_get.call_count)
        self.assertEqual(0, report.roll_calls_listed)
        self.assertEqual(1, health.skips)
        self.assertEqual(1, health.skip_reasons.get("no_bioguide_join_keys", 0))
        self.assertEqual("skipped", health.status)

    def test_rate_limit_is_visible_and_stops_the_optional_shadow_source(self):
        health = SourceHealthTracker("house_roll_call_shadow", min_attempts_for_rate=3)
        with patch(
            "extractors.house_roll_calls.requests.get",
            return_value=_Response(status_code=429),
        ):
            report = house_roll_calls.get_recent_house_roll_call_shadow(
                {"A000001"},
                {},
                health=health,
                today=date(2026, 7, 14),
            )

        self.assertEqual(0, report.roll_calls_fetched)
        self.assertTrue(health.breaker_tripped)
        self.assertEqual("http_429", health.breaker_reason)
        self.assertEqual("failed", health.status)

    def test_transient_listing_failure_retries_before_continuing(self):
        health = SourceHealthTracker("house_roll_call_shadow", min_attempts_for_rate=3)
        with patch(
            "extractors.house_roll_calls.requests.get",
            side_effect=[
                _Response(status_code=500),
                _Response(text=_listing(1)),
                _Response(text=_roll_call_xml(1, "Yea")),
            ],
        ) as mock_get, patch("extractors.house_roll_calls.time.sleep") as mock_sleep:
            report = house_roll_calls.get_recent_house_roll_call_shadow(
                {"A000001"},
                {},
                limit=1,
                health=health,
                today=date(2026, 7, 14),
            )

        self.assertEqual(3, mock_get.call_count)
        self.assertEqual(1, report.roll_calls_fetched)
        self.assertEqual("healthy", health.status)
        self.assertEqual(2, health.attempts)
        self.assertEqual(2, health.successes)
        mock_sleep.assert_called_once_with(0.5)

    def test_govtrack_reconciliation_requires_its_exact_house_vote_url(self):
        records = [
            {
                "bill_summary": "Result - https://www.govtrack.us/congress/votes/119-2026/h240",
                "vote_cast": "Yea",
            },
            {
                "bill_summary": "A similarly named Senate vote",
                "vote_cast": "Nay",
            },
        ]

        self.assertEqual(
            {"house:119:2026:240": "Yea"},
            house_roll_calls.govtrack_house_vote_casts(records),
        )

    def test_roll_call_parser_rejects_a_response_for_the_wrong_vote(self):
        with self.assertRaises(ValueError):
            house_roll_calls._parse_roll_call(
                _roll_call_xml(2, "Yea"),
                "https://example.test/roll001.xml",
                119,
                2,
                2026,
                1,
            )

    def test_roll_call_parser_rejects_an_invalid_session_label(self):
        with self.assertRaises(ValueError):
            house_roll_calls._parse_roll_call(
                _roll_call_xml(1, "Yea").replace(
                    "<session>2nd</session>", "<session>1nd</session>"
                ),
                "https://example.test/roll001.xml",
                119,
                2,
                2026,
                1,
            )


if __name__ == "__main__":
    unittest.main()
