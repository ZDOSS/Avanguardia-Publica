import unittest
from datetime import date
from unittest.mock import patch

from extractors import senate_roll_calls
from source_health import SourceHealthTracker


_HISTORICAL_YAML = """
- id:
    lis: S999
    bioguide: Z000001
  terms:
    - type: sen
      start: 2000-01-01
      end: 2006-12-31
- id:
    lis: X123
    bioguide: Z000002
  terms:
    - type: rep
      start: 2010-01-01
      end: 2014-12-31
"""


def _roll_call_xml(vote_number: int, first_vote: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<roll_call_vote>
  <congress>119</congress>
  <session>2</session>
  <congress_year>2026</congress_year>
  <vote_number>{vote_number}</vote_number>
  <vote_date>June 24, 2026,  10:30 PM</vote_date>
  <vote_question_text>On the Motion to Proceed S.J.Res. {vote_number}</vote_question_text>
  <members>
    <member><lis_member_id>S001</lis_member_id><vote_cast>{first_vote}</vote_cast></member>
    <member><lis_member_id>S002</lis_member_id><vote_cast>Nay</vote_cast></member>
    <member><lis_member_id>S999</lis_member_id><vote_cast>Present</vote_cast></member>
    <member><vote_cast>Not Voting</vote_cast></member>
  </members>
</roll_call_vote>"""


class _Response:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class SenateRollCallShadowTests(unittest.TestCase):
    def test_current_congress_session_handles_the_january_transition(self):
        self.assertEqual(
            (119, 1),
            senate_roll_calls._current_congress_session(date(2026, 1, 2)),
        )
        self.assertEqual(
            (119, 2),
            senate_roll_calls._current_congress_session(date(2026, 7, 13)),
        )
        self.assertEqual(
            (119, 2),
            senate_roll_calls._current_congress_session(date(2027, 1, 2)),
        )

    def test_menu_parser_uses_only_the_requested_congress_and_session(self):
        menu = """
            <a href="vote_119_2_00002.htm">2</a>
            <a href="vote_119_2_00001.htm">1</a>
            <a href="vote_119_1_00200.htm">prior session</a>
            <a href="vote_118_2_00300.htm">prior congress</a>
        """
        self.assertEqual([2, 1], senate_roll_calls._parse_menu(menu, 119, 2))

    def test_shadow_fetches_a_bounded_window_and_compares_only_exact_lis_ids(self):
        menu = """
            <a href="vote_119_2_00002.htm">2</a>
            <a href="vote_119_2_00001.htm">1</a>
        """
        health = SourceHealthTracker("senate_roll_call_shadow", min_attempts_for_rate=3)
        govtrack_votes = {
            "S001": {
                "senate:119:2026:2": "Yea",
                "senate:119:2026:1": "Yea",
            }
        }

        with patch(
            "extractors.senate_roll_calls.requests.get",
            side_effect=[
                _Response(text="[]"),
                _Response(text=menu),
                _Response(text=_roll_call_xml(2, "Yea")),
                _Response(text=_roll_call_xml(1, "Nay")),
            ],
        ) as mock_get:
            report = senate_roll_calls.get_recent_senate_roll_call_shadow(
                {"S001", "S002"},
                govtrack_votes,
                limit=2,
                health=health,
                today=date(2026, 7, 13),
            )

        self.assertEqual(4, mock_get.call_count)
        self.assertEqual("healthy", health.status)
        self.assertEqual(4, health.attempts)
        self.assertEqual(4, health.successes)
        self.assertEqual(2, report.roll_calls_listed)
        self.assertEqual(2, report.roll_calls_fetched)
        self.assertEqual(8, report.member_votes_seen)
        self.assertEqual(2, report.member_votes_missing_lis_id)
        self.assertEqual(4, report.exact_lis_matches)
        self.assertEqual({"S999"}, report.unmatched_lis_ids)
        self.assertEqual(1, report.govtrack_vote_cast_matches)
        self.assertEqual(1, report.govtrack_vote_cast_mismatches)
        self.assertEqual(2, report.govtrack_vote_not_observed)
        self.assertEqual(
            1,
            report.counters()["senate_roll_call_shadow_unmatched_lis_ids"],
        )

    def test_shadow_returns_early_without_lis_join_keys(self):
        health = SourceHealthTracker("senate_roll_call_shadow", min_attempts_for_rate=3)
        with patch("extractors.senate_roll_calls.requests.get") as mock_get:
            report = senate_roll_calls.get_recent_senate_roll_call_shadow(
                {"", "  "},
                {},
                health=health,
                today=date(2026, 7, 13),
            )

        self.assertEqual(0, mock_get.call_count)
        self.assertEqual(0, report.roll_calls_listed)
        self.assertEqual(1, health.skips)
        self.assertEqual(1, health.skip_reasons.get("no_lis_join_keys", 0))
        self.assertEqual("skipped", health.status)

    def test_rate_limit_is_visible_and_stops_the_optional_shadow_source(self):
        health = SourceHealthTracker("senate_roll_call_shadow", min_attempts_for_rate=3)
        with patch(
            "extractors.senate_roll_calls.requests.get",
            return_value=_Response(status_code=429),
        ):
            report = senate_roll_calls.get_recent_senate_roll_call_shadow(
                {"S001"},
                {},
                health=health,
                today=date(2026, 7, 13),
            )

        self.assertEqual(0, report.roll_calls_fetched)
        self.assertTrue(health.breaker_tripped)
        self.assertEqual("http_429", health.breaker_reason)
        self.assertEqual("failed", health.status)

    def test_shadow_uses_historical_senate_lis_ids_when_available(self):
        menu = """
            <a href="vote_119_2_00002.htm">2</a>
            <a href="vote_119_2_00001.htm">1</a>
        """
        health = SourceHealthTracker("senate_roll_call_shadow", min_attempts_for_rate=3)
        govtrack_votes = {
            "S001": {
                "senate:119:2026:2": "Yea",
                "senate:119:2026:1": "Yea",
            },
            "S999": {
                "senate:119:2026:2": "Present",
                "senate:119:2026:1": "Present",
            },
        }

        with patch(
            "extractors.senate_roll_calls.requests.get",
            side_effect=[
                _Response(text=_HISTORICAL_YAML),
                _Response(text=menu),
                _Response(text=_roll_call_xml(2, "Yea")),
                _Response(text=_roll_call_xml(1, "Nay")),
            ],
        ) as mock_get:
            report = senate_roll_calls.get_recent_senate_roll_call_shadow(
                {"S001"},
                govtrack_votes,
                limit=2,
                health=health,
                today=date(2026, 7, 13),
            )

        self.assertEqual(4, mock_get.call_count)
        self.assertEqual(8, report.member_votes_seen)
        self.assertEqual(2, report.member_votes_missing_lis_id)
        self.assertEqual({"S002"}, report.unmatched_lis_ids)
        self.assertEqual(4, report.exact_lis_matches)
        self.assertEqual(3, report.govtrack_vote_cast_matches)
        self.assertEqual(1, report.govtrack_vote_cast_mismatches)
        self.assertEqual(0, report.govtrack_vote_not_observed)
        self.assertEqual(1, report.historical_lis_ids_loaded)

    def test_historical_lis_ids_failure_modes_are_nonfatal(self):
        failure_cases = [
            (
                _Response(status_code=200, text="not-a-yaml-list"),
                "historical_parse_error",
            ),
            (
                _Response(status_code=500, text="service unavailable"),
                "historical_http_500",
            ),
        ]

        for response, reason in failure_cases:
            with self.subTest(reason=reason):
                health = SourceHealthTracker("senate_roll_call_shadow", min_attempts_for_rate=3)
                with patch(
                    "extractors.senate_roll_calls.requests.get",
                    return_value=response,
                ) as mock_get:
                    ids = senate_roll_calls._historical_senate_lis_ids(health=health)

                self.assertEqual(set(), ids)
                self.assertEqual(1, mock_get.call_count)
                self.assertEqual(1, health.skips)
                self.assertEqual(1, health.skip_reasons.get(reason, 0))

    def test_shadow_normalizes_roster_and_historical_lis_ids(self):
        menu = """
            <a href="vote_119_2_00002.htm">2</a>
            <a href="vote_119_2_00001.htm">1</a>
        """
        historical_yaml = """
- id:
    lis: s999
    bioguide: Z000001
  terms:
    - type: sen
      start: 2000-01-01
      end: 2006-12-31
"""
        health = SourceHealthTracker("senate_roll_call_shadow", min_attempts_for_rate=3)

        with patch(
            "extractors.senate_roll_calls.requests.get",
            side_effect=[
                _Response(text=historical_yaml),
                _Response(text=menu),
                _Response(text=_roll_call_xml(2, "Yea")),
                _Response(text=_roll_call_xml(1, "Nay")),
            ],
        ) as mock_get:
            report = senate_roll_calls.get_recent_senate_roll_call_shadow(
                {" s001 "},
                {
                    "S001": {
                        "senate:119:2026:2": "Yea",
                        "senate:119:2026:1": "Yea",
                    },
                    "s999": {
                        "senate:119:2026:2": "Present",
                        "senate:119:2026:1": "Present",
                    },
                },
                limit=2,
                health=health,
                today=date(2026, 7, 13),
            )

        self.assertEqual(4, mock_get.call_count)
        self.assertEqual(1, report.historical_lis_ids_loaded)
        self.assertEqual({"S002"}, report.unmatched_lis_ids)

    def test_govtrack_reconciliation_requires_its_exact_senate_vote_url(self):
        records = [
            {
                "bill_summary": "Result - https://www.govtrack.us/congress/votes/119-2026/s192",
                "vote_cast": "Yea",
            },
            {
                "bill_summary": "A similarly named House vote",
                "vote_cast": "Nay",
            },
        ]

        self.assertEqual(
            {"senate:119:2026:192": "Yea"},
            senate_roll_calls.govtrack_senate_vote_casts(records),
        )

    def test_roll_call_parser_rejects_a_response_for_the_wrong_vote(self):
        with self.assertRaises(ValueError):
            senate_roll_calls._parse_roll_call(
                _roll_call_xml(2, "Yea"),
                "https://example.test/vote_119_2_00001.xml",
                119,
                2,
                1,
            )


if __name__ == "__main__":
    unittest.main()
