import unittest
from pathlib import Path


class OfficialVotingRecordsReadMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        migration_path = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "0031_official_voting_records_read_surface.sql"
        )
        cls.sql = migration_path.read_text(encoding="utf-8")
        function_start = cls.sql.index(
            "CREATE FUNCTION public.get_canonical_voting_records_v2"
        )
        function_end = cls.sql.index("$function$;", function_start)
        cls.function_sql = cls.sql[function_start:function_end]

        repair_path = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "0032_official_voting_records_query_repair.sql"
        )
        cls.repair_sql = repair_path.read_text(encoding="utf-8")
        repair_function_start = cls.repair_sql.index(
            "CREATE OR REPLACE FUNCTION public.get_canonical_voting_records_v2"
        )
        repair_function_end = cls.repair_sql.index(
            "$function$;",
            repair_function_start,
        )
        cls.repair_function_sql = cls.repair_sql[
            repair_function_start:repair_function_end
        ]

        deduplication_repair_path = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "0033_official_voting_records_deduplication_repair.sql"
        )
        cls.deduplication_repair_sql = deduplication_repair_path.read_text(
            encoding="utf-8"
        )
        deduplication_function_start = cls.deduplication_repair_sql.index(
            "CREATE OR REPLACE FUNCTION public.get_canonical_voting_records_v2"
        )
        deduplication_function_end = cls.deduplication_repair_sql.index(
            "$function$;",
            deduplication_function_start,
        )
        cls.deduplication_function_sql = cls.deduplication_repair_sql[
            deduplication_function_start:deduplication_function_end
        ]

    def test_requires_the_completed_senate_rollout(self):
        self.assertIn(
            "'0030_senate_roll_call_production_enablement'",
            self.sql,
        )
        self.assertIn("migration_version = 30", self.sql)
        self.assertIn(
            "migration 0030_senate_roll_call_production_enablement must be applied first",
            self.sql,
        )

    def test_read_rpc_is_person_aware_and_security_definer(self):
        self.assertIn("LANGUAGE sql", self.function_sql)
        self.assertIn("STABLE", self.function_sql)
        self.assertIn("SECURITY DEFINER", self.function_sql)
        self.assertIn("SET search_path = ''", self.function_sql)
        self.assertIn(
            "public.get_canonical_person_legacy_ids(p_id)",
            self.function_sql,
        )
        self.assertIn("person.status = 'active'", self.function_sql)

    def test_exposes_only_active_verified_reviewed_official_facts(self):
        for contract in (
            "person_vote_source.record_status = 'active'",
            "roll_call_source.record_status = 'active'",
            "person_vote_source.retired_at IS NULL",
            "roll_call_source.retired_at IS NULL",
            "person_vote_source.verified_lane = 'verified'",
            "roll_call_source.verified_lane = 'verified'",
            "source_system.source_kind = 'government'",
            "source_system.trust_level = 'official'",
            "source_system.verified = true",
            "catalog_source.status = 'approved'",
            "catalog_source.repo_fit = 'wired'",
            "catalog_endpoint.status = 'approved'",
        ):
            self.assertIn(contract, self.function_sql)

        for private_field in ("raw_payload_ref", "payload_hash", "metadata"):
            self.assertNotIn(private_field, self.function_sql)

    def test_scopes_official_rows_to_the_two_reviewed_vote_sources(self):
        for contract in (
            "roll_call.chamber = 'house'",
            "roll_call_source.source_system_key = 'house-clerk'",
            "'house-clerk-roll-call-xml'",
            "roll_call_source.source_endpoint_slug = 'evs-roll-call-feed'",
            "roll_call.chamber = 'senate'",
            "roll_call_source.source_system_key = 'senate-lis'",
            "roll_call_source.source_catalog_slug = 'senate-roll-call-xml'",
            "roll_call_source.source_endpoint_slug = 'lis-roll-call-feed'",
        ):
            self.assertIn(contract, self.function_sql)

    def test_keeps_legacy_coverage_and_narrowly_deduplicates_govtrack(self):
        self.assertIn("FROM public.voting_records AS legacy_vote", self.function_sql)
        self.assertIn("'legacy'::text AS record_origin", self.function_sql)
        self.assertIn("legacy_vote.roll_call_id LIKE 'govtrack:%'", self.function_sql)
        self.assertIn("official_vote.vote_date = legacy_vote.vote_date", self.function_sql)
        self.assertIn(
            "official_vote.roll_call_id = legacy_vote.roll_call_id",
            self.function_sql,
        )
        self.assertIn("btrim(official_vote.bill_name)", self.function_sql)
        self.assertIn("btrim(legacy_vote.bill_name)", self.function_sql)
        self.assertNotIn("legacy_vote.jurisdiction IS NULL", self.function_sql)

    def test_keeps_private_tables_private_and_grants_only_the_rpc(self):
        self.assertNotIn(
            "GRANT SELECT ON TABLE public.legislative_roll_calls",
            self.sql,
        )
        self.assertNotIn(
            "GRANT SELECT ON TABLE public.person_roll_call_votes",
            self.sql,
        )
        self.assertIn(
            "REVOKE EXECUTE ON FUNCTION public.get_canonical_voting_records_v2",
            self.sql,
        )
        self.assertIn(
            ") TO anon, authenticated;",
            self.sql,
        )

    def test_records_forward_only_marker_and_reloads_postgrest(self):
        self.assertIn(
            "'0031_official_voting_records_read_surface',\n    31,",
            self.sql,
        )
        self.assertIn("'scraper_preflight_required', true", self.sql)
        self.assertIn("NOTIFY pgrst, 'reload schema';", self.sql)
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))

    def test_query_repair_requires_the_exact_applied_0031_contract(self):
        self.assertIn("'0031_official_voting_records_read_surface'", self.repair_sql)
        self.assertIn("migration_version = 31", self.repair_sql)
        self.assertIn(
            "v_body_md5 IS DISTINCT FROM '67534a64b5bca1a74fbdbe7b511ff928'",
            self.repair_sql,
        )
        self.assertIn("v_language IS DISTINCT FROM 'sql'", self.repair_sql)
        self.assertIn("v_security_definer IS DISTINCT FROM true", self.repair_sql)
        self.assertIn("v_volatility IS DISTINCT FROM 's'", self.repair_sql)
        self.assertIn("ARRAY['search_path=\"\"']::text[]", self.repair_sql)

    def test_query_repair_resolves_one_person_before_fact_queries(self):
        self.assertIn("LANGUAGE plpgsql", self.repair_function_sql)
        self.assertIn("SECURITY DEFINER", self.repair_function_sql)
        self.assertIn("SET search_path = ''", self.repair_function_sql)
        resolver = self.repair_function_sql.index(
            "FROM public.get_canonical_person_legacy_ids(p_id) AS resolved"
        )
        return_query = self.repair_function_sql.index("RETURN QUERY", resolver)
        self.assertLess(resolver, return_query)
        self.assertIn("count(DISTINCT resolved.person_id)", self.repair_function_sql)
        self.assertIn("IF v_person_count <> 1", self.repair_function_sql)

    def test_query_repair_constrains_indexed_branches_before_normalizing(self):
        self.assertIn(
            "person_vote.person_id = v_person_id",
            self.repair_function_sql,
        )
        self.assertIn(
            "legacy_vote.person_id = v_person_id",
            self.repair_function_sql,
        )
        self.assertIn(
            "legacy_vote.politician_id = ANY(v_legacy_politician_ids)",
            self.repair_function_sql,
        )
        self.assertGreaterEqual(
            self.repair_function_sql.count("END = v_vote_cast_key"),
            2,
        )
        self.assertNotIn("CROSS JOIN params", self.repair_function_sql)

    def test_query_repair_preserves_security_and_forward_only_history(self):
        self.assertNotIn(
            "GRANT SELECT ON TABLE public.legislative_roll_calls",
            self.repair_sql,
        )
        self.assertIn(
            "REVOKE EXECUTE ON FUNCTION public.get_canonical_voting_records_v2",
            self.repair_sql,
        )
        self.assertIn(") TO anon, authenticated;", self.repair_sql)
        self.assertIn(
            "'0032_official_voting_records_query_repair',\n    32,",
            self.repair_sql,
        )
        self.assertIn("'scraper_preflight_required', true", self.repair_sql)
        self.assertIn("NOTIFY pgrst, 'reload schema';", self.repair_sql)
        self.assertTrue(self.repair_sql.rstrip().endswith("COMMIT;"))

    def test_deduplication_repair_requires_the_exact_applied_0032_contract(self):
        self.assertIn(
            "'0032_official_voting_records_query_repair'",
            self.deduplication_repair_sql,
        )
        self.assertIn("migration_version = 32", self.deduplication_repair_sql)
        self.assertIn(
            "v_body_md5 IS DISTINCT FROM '7ae68c60106645c0182c669fa1ce13aa'",
            self.deduplication_repair_sql,
        )
        self.assertIn(
            "v_language IS DISTINCT FROM 'plpgsql'",
            self.deduplication_repair_sql,
        )
        self.assertIn(
            "v_security_definer IS DISTINCT FROM true",
            self.deduplication_repair_sql,
        )
        self.assertIn(
            "ARRAY['search_path=\"\"']::text[]",
            self.deduplication_repair_sql,
        )

    def test_deduplication_repair_retains_ambiguous_govtrack_signatures(self):
        for preserved_contract in (
            "person_vote.person_id = v_person_id",
            "person_vote_source.record_status = 'active'",
            "person_vote_source.verified_lane = 'verified'",
            "source_system.source_kind = 'government'",
            "source_system.trust_level = 'official'",
            "catalog_source.status = 'approved'",
            "catalog_source.repo_fit = 'wired'",
            "roll_call_source.source_system_key = 'house-clerk'",
            "roll_call_source.source_system_key = 'senate-lis'",
            "legacy_vote.person_id = v_person_id",
            "legacy_vote.politician_id = ANY(v_legacy_politician_ids)",
        ):
            self.assertIn(preserved_contract, self.deduplication_function_sql)

        self.assertIn(
            "unambiguous_official_signatures AS (",
            self.deduplication_function_sql,
        )
        self.assertIn(
            "HAVING count(DISTINCT official_vote.roll_call_id) = 1",
            self.deduplication_function_sql,
        )
        self.assertIn(
            "official_vote.roll_call_id = legacy_vote.roll_call_id",
            self.deduplication_function_sql,
        )
        self.assertIn(
            "OR legacy_vote.roll_call_id NOT LIKE 'govtrack:%'",
            self.deduplication_function_sql,
        )
        self.assertIn(
            "OR NOT EXISTS (\n                  SELECT 1\n"
            "                  FROM unambiguous_official_signatures",
            self.deduplication_function_sql,
        )
        self.assertNotIn(
            "official_vote.roll_call_id = legacy_vote.roll_call_id\n"
            "                  OR legacy_vote.roll_call_id LIKE 'govtrack:%'",
            self.deduplication_function_sql,
        )

    def test_deduplication_repair_preserves_security_and_records_marker(self):
        self.assertNotIn(
            "GRANT SELECT ON TABLE public.legislative_roll_calls",
            self.deduplication_repair_sql,
        )
        self.assertIn(
            "REVOKE EXECUTE ON FUNCTION public.get_canonical_voting_records_v2",
            self.deduplication_repair_sql,
        )
        self.assertIn(
            ") TO anon, authenticated;",
            self.deduplication_repair_sql,
        )
        self.assertIn(
            "'0033_official_voting_records_deduplication_repair',\n    33,",
            self.deduplication_repair_sql,
        )
        self.assertIn(
            "'scraper_preflight_required', true",
            self.deduplication_repair_sql,
        )
        self.assertIn(
            "NOTIFY pgrst, 'reload schema';",
            self.deduplication_repair_sql,
        )
        self.assertTrue(self.deduplication_repair_sql.rstrip().endswith("COMMIT;"))


if __name__ == "__main__":
    unittest.main()
