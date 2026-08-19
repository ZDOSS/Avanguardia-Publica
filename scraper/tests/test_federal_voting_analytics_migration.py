import re
import unittest
from pathlib import Path


class FederalVotingAnalyticsMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        migration_path = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "0038_canonical_federal_voting_analytics.sql"
        )
        cls.sql = migration_path.read_text(encoding="utf-8")

        view_start = cls.sql.index(
            "CREATE VIEW public.canonical_verified_federal_roll_call_votes_v1"
        )
        view_end = cls.sql.index(
            "REVOKE ALL ON TABLE public.canonical_verified_federal_roll_call_votes_v1",
            view_start,
        )
        cls.view_sql = cls.sql[view_start:view_end]

        cls.function_sql = {}
        for function_name in (
            "get_canonical_federal_voting_summary_v1",
            "get_canonical_federal_voting_alignment_v1",
            "get_canonical_federal_voting_comparison_v1",
        ):
            function_start = cls.sql.index(
                f"CREATE FUNCTION public.{function_name}"
            )
            function_end = cls.sql.index("$function$;", function_start)
            cls.function_sql[function_name] = cls.sql[
                function_start:function_end
            ]

    def test_requires_the_complete_measure_aware_vote_surface(self):
        self.assertIn(
            "migration_key = '0037_congress_gov_measure_read_surface'",
            self.sql,
        )
        self.assertIn("migration_version = 37", self.sql)
        self.assertIn(
            "migration 0037_congress_gov_measure_read_surface must be applied first",
            self.sql,
        )

    def test_internal_read_model_is_security_invoker_owner_only_and_pushdown_safe(self):
        self.assertIn("security_invoker = true", self.view_sql)
        self.assertNotIn("security_barrier = true", self.view_sql)
        self.assertIn("indexed person/scope filters must be eligible for pushdown", self.sql)
        self.assertIn(
            "REVOKE ALL ON TABLE "
            "public.canonical_verified_federal_roll_call_votes_v1\n"
            "    FROM PUBLIC, anon, authenticated, service_role;",
            self.sql,
        )
        self.assertNotIn(
            "GRANT SELECT ON TABLE "
            "public.canonical_verified_federal_roll_call_votes_v1",
            self.sql,
        )

    def test_internal_read_model_accepts_only_active_reviewed_official_facts(self):
        for contract in (
            "person.status = 'active'",
            "person_vote_source.record_type = 'person_roll_call_vote'",
            "person_vote_source.record_status = 'active'",
            "person_vote_source.retired_at IS NULL",
            "person_vote_source.verified_lane = 'verified'",
            "roll_call_source.record_type = 'legislative_roll_call'",
            "roll_call_source.record_status = 'active'",
            "roll_call_source.retired_at IS NULL",
            "roll_call_source.verified_lane = 'verified'",
            "source_system.source_kind = 'government'",
            "source_system.trust_level = 'official'",
            "source_system.verified = true",
            "catalog_source.status = 'approved'",
            "catalog_source.repo_fit = 'wired'",
            "catalog_source.verified_lane = 'verified'",
            "catalog_endpoint.status = 'approved'",
        ):
            self.assertIn(contract, self.view_sql)

        for exact_source_contract in (
            "roll_call_source.source_system_key = 'house-clerk'",
            "roll_call_source.source_catalog_slug = 'house-clerk-roll-call-xml'",
            "roll_call_source.source_endpoint_slug = 'evs-roll-call-feed'",
            "roll_call.canonical_roll_call_key ~ '^house:'",
            "roll_call_source.source_system_key = 'senate-lis'",
            "roll_call_source.source_catalog_slug = 'senate-roll-call-xml'",
            "roll_call_source.source_endpoint_slug = 'lis-roll-call-feed'",
            "roll_call.canonical_roll_call_key ~ '^senate:'",
        ):
            self.assertIn(exact_source_contract, self.view_sql)

    def test_summary_is_role_scoped_and_keeps_participation_categories_visible(self):
        summary = self.function_sql["get_canonical_federal_voting_summary_v1"]
        self.assertIn("public.get_canonical_person_legacy_ids(p_id)", summary)
        self.assertIn("person.status = 'active'", summary)
        self.assertIn("GROUP BY vote.chamber, vote.congress", summary)
        self.assertIn("vote.vote_cast <> 'not_voting'", summary)
        self.assertIn("vote.vote_cast IN ('yea', 'nay')", summary)
        self.assertIn("vote.vote_cast = 'present'", summary)
        self.assertIn("vote.vote_cast = 'not_voting'", summary)
        self.assertIn("        10,", summary)
        self.assertIn("LIMIT 20", summary)

    def test_alignment_is_exact_bounded_and_has_a_real_sample_floor(self):
        alignment = self.function_sql[
            "get_canonical_federal_voting_alignment_v1"
        ]
        for contract in (
            "vote.person_id = v_person_id",
            "vote.chamber = v_chamber",
            "vote.congress = v_congress",
            "vote.vote_cast IN ('yea', 'nay')",
            "peer_vote.roll_call_source_record_id =",
            "target_vote.roll_call_source_record_id",
            "peer_vote.person_id <> v_person_id",
            "peer_vote.vote_cast IN ('yea', 'nay')",
            "HAVING count(*) >= 10",
            "score.agreement_rate DESC",
            "score.agreement_rate,",
            "ranked.aligned_rank <= v_limit",
            "ranked.differing_rank <= v_limit",
            "GREATEST(COALESCE(result_limit_per_side, 6), 1)",
            "        12",
        ):
            self.assertIn(contract, alignment)

        self.assertIn(
            "public.get_canonical_politician_header(\n"
            "        ranked.peer_person_id",
            alignment,
        )
        self.assertNotIn("public.voting_records", alignment)

    def test_optimized_peer_joins_preserve_the_verified_source_contract(self):
        for function_name in (
            "get_canonical_federal_voting_alignment_v1",
            "get_canonical_federal_voting_comparison_v1",
        ):
            function_sql = self.function_sql[function_name]
            for contract in (
                "peer_person.status = 'active'",
                "peer_vote_source.id = peer_vote.source_record_id",
                "peer_vote_source.person_id = peer_vote.person_id",
                "peer_vote_source.record_type = 'person_roll_call_vote'",
                "peer_vote_source.record_status = 'active'",
                "peer_vote_source.retired_at IS NULL",
                "peer_vote_source.verified_lane = 'verified'",
                "peer_vote_source.source_system_key =",
                "target_vote.source_system_key",
                "peer_vote_source.source_catalog_slug =",
                "target_vote.source_catalog_slug",
                "peer_vote_source.source_endpoint_slug =",
                "target_vote.source_endpoint_slug",
                "peer_vote_source.source_url = target_vote.source_url",
            ):
                self.assertIn(contract, function_sql)

    def test_pairwise_evidence_matches_the_metric_and_is_paginated(self):
        comparison = self.function_sql[
            "get_canonical_federal_voting_comparison_v1"
        ]
        for contract in (
            "v_person_id = v_peer_person_id",
            "peer_vote.person_id = v_peer_person_id",
            "target_vote.person_id = v_person_id",
            "target_vote.chamber = v_chamber",
            "target_vote.congress = v_congress",
            "target_vote.vote_cast IN ('yea', 'nay')",
            "peer_vote.vote_cast IN ('yea', 'nay')",
            "WHEN target_vote.vote_cast = peer_vote.vote_cast THEN 'agree'",
            "v_filter NOT IN ('agree', 'differ')",
            "WHERE v_filter IS NULL OR shared_vote.comparison = v_filter",
            "GREATEST(COALESCE(result_limit, 26), 0), 51",
            "GREATEST(COALESCE(result_offset, 0), 0), 5000",
            "LIMIT v_limit",
            "OFFSET v_offset",
        ):
            self.assertIn(contract, comparison)

        self.assertNotIn("public.voting_records", comparison)

    def test_pairwise_evidence_exposes_only_bounded_verified_measure_metadata(self):
        comparison = self.function_sql[
            "get_canonical_federal_voting_comparison_v1"
        ]
        for contract in (
            "measure_link.link_basis =",
            "'exact_official_measure_identifier'",
            "measure_source.source_system_key = 'congress-gov'",
            "measure_source.record_status = 'active'",
            "measure_source.retired_at IS NULL",
            "measure_source.verified_lane = 'verified'",
            "measure_catalog_source.status = 'approved'",
            "measure_catalog_source.repo_fit = 'wired'",
            "measure_catalog_endpoint.status = 'approved'",
            "measure.official_url LIKE 'https://www.congress.gov/%'",
            "LIMIT 20",
        ):
            self.assertIn(contract, comparison)

        for private_presentation in (
            "raw_payload_ref",
            "payload_hash",
            "measure.metadata",
            "measure_link.metadata",
            "measure_source.metadata",
        ):
            self.assertNotIn(private_presentation, comparison)

    def test_public_contract_is_security_definer_without_private_table_grants(self):
        for function_name, signature in (
            ("get_canonical_federal_voting_summary_v1", "uuid"),
            (
                "get_canonical_federal_voting_alignment_v1",
                "uuid,text,integer,integer",
            ),
            (
                "get_canonical_federal_voting_comparison_v1",
                "uuid,uuid,text,integer,text,integer,integer",
            ),
        ):
            function_sql = self.function_sql[function_name]
            self.assertIn("STABLE", function_sql)
            self.assertIn("SECURITY DEFINER", function_sql)
            self.assertIn("SET search_path = ''", function_sql)
            self.assertIn(
                f"public.{function_name}({signature})",
                self.sql.replace("\n", "").replace(" ", ""),
            )

        for table in (
            "source_records",
            "legislative_roll_calls",
            "person_roll_call_votes",
            "legislative_measures",
            "legislative_roll_call_measure_links",
        ):
            self.assertNotIn(f"GRANT SELECT ON TABLE public.{table}", self.sql)

        self.assertGreaterEqual(self.sql.count(") TO anon, authenticated;"), 3)

    def test_migration_is_read_only_apart_from_its_forward_marker(self):
        mutations = re.findall(
            r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+public\.([a-z0-9_]+)",
            self.sql,
            flags=re.IGNORECASE,
        )
        self.assertEqual(["schema_migrations"], [table.lower() for table in mutations])

    def test_records_marker_and_advances_preflight(self):
        self.assertIn(
            "'0038_canonical_federal_voting_analytics',\n    38,",
            self.sql,
        )
        self.assertIn("'legacy_vote_rows_included', false", self.sql)
        self.assertIn("'scraper_write_contract_changed', false", self.sql)
        self.assertIn("'scraper_preflight_required', true", self.sql)
        self.assertIn("NOTIFY pgrst, 'reload schema';", self.sql)
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))


if __name__ == "__main__":
    unittest.main()
