import logging
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from supabase import create_client, Client

from government_classification import normalize_government_classification, normalize_location_fields
from identity import (
    ExistingIdentity,
    IdentityKey,
    IdentityResolution,
    IdentityResolver,
    packet_from_legacy_politician,
    trusted_external_keys,
)

logger = logging.getLogger(__name__)

# Stable, non-federal identity schemes carried in external_ids, most-trusted first.
# A row carrying any of these is owned by a non-federal source (state legislators via
# OpenStates, federal exec/judicial via Wikidata) and must never be matched by the
# federal bioguide name-fallback. Single source of truth so the match logic and the
# fallback guard can never drift apart.
_STABLE_SCHEMES = ("openstates", "wikidata")


def _json_compatible(value):
    """Recursively convert temporal values before handing payloads to PostgREST."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value


class IdentityResolutionConflict(RuntimeError):
    """Raised before a hub mutation when deterministic identity evidence conflicts."""


class SupabaseLoader:
    def __init__(self, url: str, key: str, summary=None):
        self.url = url
        self.key = key
        self.summary = summary
        if url and key:
            self.supabase: Client = create_client(url, key)
            print("Supabase client initialized.")
        else:
            self.supabase = None
            print("Warning: SUPABASE_URL or SUPABASE_KEY is not set. Running in dry-run mode.")
        self.person_id_by_politician_id = {}
        self.identity_resolver = IdentityResolver(summary=self.summary)
        self.identity_observer_loaded = False

    def _increment(self, key: str, amount: int = 1) -> None:
        if self.summary:
            self.summary.increment(key, amount)

    def _reset_client(self) -> None:
        if self.url and self.key:
            self.supabase = create_client(self.url, self.key)

    @staticmethod
    def _is_non_retryable_supabase_error(exc: Exception) -> bool:
        message = str(exc).lower()
        non_retryable_markers = (
            # Unique violations are expected for idempotent mention inserts. They often
            # include an HTTP/2 transport string, so check them before transient markers.
            "duplicate key value violates unique constraint",
            "'code': '23505'",
            '"code": "23505"',
        )
        return any(marker in message for marker in non_retryable_markers)

    @staticmethod
    def _is_transient_supabase_error(exc: Exception) -> bool:
        if SupabaseLoader._is_non_retryable_supabase_error(exc):
            return False

        message = str(exc).lower()
        transient_markers = (
            "connectionterminated",
            "connection terminated",
            "remote protocol error",
            "server disconnected",
            "read timed out",
            "readtimeout",
            "connecttimeout",
            "connection reset",
            "temporarily unavailable",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
            "http/2",
            "409 conflict",
            "503",
            "504",
            "502",
        )
        return any(marker in message for marker in transient_markers)

    def execute_supabase(self, operation, description: str, retries: int = 3):
        """
        Execute a Supabase request with a fresh-client retry for transient transport
        failures. Schema/API errors still bubble immediately.
        """
        for attempt in range(1, retries + 1):
            try:
                return operation()
            except Exception as exc:
                if attempt >= retries or not self._is_transient_supabase_error(exc):
                    raise
                wait_seconds = 2 ** (attempt - 1)
                logger.warning(
                    "Transient Supabase error during %s (attempt %d/%d): %s. "
                    "Refreshing client and retrying in %ss.",
                    description,
                    attempt,
                    retries,
                    exc,
                    wait_seconds,
                )
                self._increment("supabase_transient_retries")
                self._reset_client()
                time.sleep(wait_seconds)

    def _select_all_rows(
        self,
        table_name: str,
        columns: str,
        page_size: int = 1000,
        eq_filters: tuple[tuple[str, object], ...] = (),
    ) -> list[dict]:
        rows = []
        start = 0
        while True:
            end = start + page_size - 1
            def operation(start=start, end=end):
                query = self.supabase.table(table_name).select(columns)
                for column, value in eq_filters:
                    query = query.eq(column, value)
                return query.range(start, end).execute()

            resp = self.execute_supabase(
                operation,
                f"load {table_name} identity observer rows",
            )
            batch = resp.data or []
            rows.extend(batch)
            if len(batch) < page_size:
                return rows
            start += page_size

    def _ensure_identity_observer_loaded(self) -> None:
        if self.identity_observer_loaded or not self.supabase:
            return

        active_people = self._select_all_rows(
            "people",
            "id",
            eq_filters=(("status", "active"),),
        )
        active_person_ids = {row.get("id") for row in active_people if row.get("id")}
        external_rows = self._select_all_rows(
            "person_external_ids",
            "person_id,source_system_key,external_id_type,external_id,is_trusted",
            eq_filters=(("is_trusted", True),),
        )
        legacy_rows = self._select_all_rows(
            "legacy_profile_redirects",
            "legacy_politician_id,person_id",
        )

        identity_data = defaultdict(lambda: {"keys": set(), "legacy_ids": set()})
        loaded_external_ids = 0
        loaded_legacy_redirects = 0

        for row in external_rows:
            person_id = row.get("person_id")
            if person_id not in active_person_ids:
                continue
            source_system_key = str(row.get("source_system_key") or "").strip()
            external_id_type = str(row.get("external_id_type") or "").strip()
            external_id = str(row.get("external_id") or "").strip()
            if not person_id or not source_system_key or not external_id_type or not external_id:
                continue
            identity_data[person_id]["keys"].add(
                (source_system_key, external_id_type, external_id)
            )
            loaded_external_ids += 1

        for row in legacy_rows:
            person_id = row.get("person_id")
            if person_id not in active_person_ids:
                continue
            legacy_politician_id = str(row.get("legacy_politician_id") or "").strip()
            if not person_id or not legacy_politician_id:
                continue
            identity_data[person_id]["legacy_ids"].add(legacy_politician_id)
            loaded_legacy_redirects += 1

        resolver = IdentityResolver(summary=self.summary)
        for person_id, data in identity_data.items():
            deterministic_keys = tuple(
                sorted(
                    IdentityKey(
                        source_system_key=source_system_key,
                        external_id_type=external_id_type,
                        external_id=external_id,
                    )
                    for source_system_key, external_id_type, external_id in data["keys"]
                )
            )
            legacy_ids = sorted(data["legacy_ids"])
            if legacy_ids:
                for legacy_politician_id in legacy_ids:
                    resolver.add_existing_identity(
                        ExistingIdentity(
                            person_id=person_id,
                            legacy_politician_id=legacy_politician_id,
                            deterministic_keys=deterministic_keys,
                        )
                    )
            else:
                resolver.add_existing_identity(
                    ExistingIdentity(
                        person_id=person_id,
                        deterministic_keys=deterministic_keys,
                    )
                )

        self.identity_resolver = resolver
        self.identity_observer_loaded = True
        self._increment("identity_observer_people_loaded", len(identity_data))
        self._increment("identity_observer_external_ids_loaded", loaded_external_ids)
        self._increment("identity_observer_legacy_redirects_loaded", loaded_legacy_redirects)

    def observe_politician_identity(self, politician_id: str, member_data: dict):
        if not self.supabase or not politician_id or politician_id == "dummy-uuid":
            return None

        try:
            self._ensure_identity_observer_loaded()
            row = dict(member_data)
            row["id"] = politician_id
            resolution = self.identity_resolver.resolve(packet_from_legacy_politician(row))
        except Exception as e:
            logger.warning("Identity observer failed for %s: %s", politician_id, e)
            self._increment("identity_observer_errors")
            return None

        self._increment("identity_observer_packets_checked")
        self._increment(f"identity_observer_{resolution.action}")
        if resolution.blocked_reason:
            self._increment(f"identity_observer_blocked_{resolution.blocked_reason}")
        if resolution.action == "blocked_conflict":
            logger.warning(
                "Identity observer blocked %s for %s: %s",
                resolution.blocked_reason,
                member_data.get("full_name") or politician_id,
                politician_id,
            )
        if resolution.action in ("blocked_conflict", "pending_review"):
            self.record_identity_resolution_candidate(politician_id, member_data, resolution)
        return resolution

    @staticmethod
    def _identity_key_evidence(keys: tuple[IdentityKey, ...]) -> list[dict]:
        return [
            {
                "source_system_key": key.source_system_key,
                "external_id_type": key.external_id_type,
                "external_id": key.external_id,
            }
            for key in keys
        ]

    @staticmethod
    def _identity_candidate_type(resolution: IdentityResolution) -> str:
        if resolution.action == "blocked_conflict":
            reason = resolution.blocked_reason or "unknown"
            return f"identity_observer_blocked_{reason}"
        if resolution.pending_candidate:
            return f"identity_observer_pending_{resolution.pending_candidate.candidate_type}"
        return f"identity_observer_{resolution.action}"

    @staticmethod
    def _identity_candidate_status(_resolution: IdentityResolution) -> str:
        return "pending"

    @staticmethod
    def _identity_candidate_person_fields(resolution: IdentityResolution) -> dict:
        source_person_id = None
        candidate_person_id = None

        if len(resolution.legacy_person_ids) == 1:
            source_person_id = resolution.legacy_person_ids[0]
        elif resolution.person_id:
            source_person_id = resolution.person_id

        if len(resolution.matching_person_ids) == 1:
            candidate_person_id = resolution.matching_person_ids[0]

        return {
            "source_person_id": source_person_id,
            "candidate_person_id": candidate_person_id,
        }

    def _identity_candidate_evidence(
        self,
        politician_id: str | None,
        member_data: dict,
        resolution: IdentityResolution,
    ) -> dict:
        evidence = {
            "source": "scraper_identity_observer",
            "observer_action": resolution.action,
            "blocked_reason": resolution.blocked_reason,
            "legacy_politician_id": politician_id,
            "source_system_key": member_data.get("source_system_key"),
            "source_record_key": member_data.get("source_record_key"),
            "source_url": member_data.get("source_url"),
            "full_name": member_data.get("full_name"),
            "current_office": member_data.get("current_office"),
            "party": member_data.get("party"),
            "state": member_data.get("state"),
            "district": member_data.get("district"),
            "deterministic_keys": self._identity_key_evidence(resolution.deterministic_keys),
            "matching_person_ids": list(resolution.matching_person_ids),
            "legacy_person_ids": list(resolution.legacy_person_ids),
        }
        if resolution.pending_candidate:
            evidence["pending_candidate"] = {
                "candidate_type": resolution.pending_candidate.candidate_type,
                "evidence": resolution.pending_candidate.evidence,
                "score": resolution.pending_candidate.score,
            }
        return evidence

    def record_identity_resolution_candidate(
        self,
        politician_id: str | None,
        member_data: dict,
        resolution: IdentityResolution,
    ) -> None:
        if not self.supabase:
            return

        try:
            candidate_type = self._identity_candidate_type(resolution)
            score = (
                resolution.pending_candidate.score
                if resolution.pending_candidate
                else None
            )
            payload = {
                "candidate_type": candidate_type,
                "source_legacy_politician_id": politician_id,
                "candidate_legacy_politician_id": politician_id,
                "status": self._identity_candidate_status(resolution),
                "score": score,
                "evidence": self._identity_candidate_evidence(
                    politician_id,
                    member_data,
                    resolution,
                ),
                **self._identity_candidate_person_fields(resolution),
            }

            def select_existing_candidate():
                query = (
                    self.supabase.table("identity_resolution_candidates")
                    .select("id,status,candidate_legacy_politician_id")
                    .eq("candidate_type", candidate_type)
                )
                if politician_id:
                    query = query.eq("source_legacy_politician_id", politician_id)
                else:
                    query = query.is_("source_legacy_politician_id", "null").contains(
                        "evidence",
                        {
                            "source_system_key": member_data.get("source_system_key"),
                            "source_record_key": member_data.get("source_record_key"),
                        },
                    )
                return query.execute()

            existing = self.execute_supabase(
                select_existing_candidate,
                f"select identity resolution candidate {candidate_type} for {politician_id}",
            )
            matching_rows = [
                row
                for row in (existing.data or [])
                if row.get("candidate_legacy_politician_id") in (None, politician_id)
            ]
            reviewed_row = next(
                (
                    row
                    for row in matching_rows
                    if row.get("status") in ("approved", "rejected", "blocked")
                ),
                None,
            )
            existing_row = reviewed_row or next(
                (
                    row
                    for row in matching_rows
                    if row.get("candidate_legacy_politician_id") == politician_id
                ),
                None,
            )
            existing_row = existing_row or next(iter(matching_rows), {})
            existing_id = existing_row.get("id")
            if existing_id:
                if reviewed_row:
                    self._increment("identity_observer_candidates_skipped_reviewed")
                    return
                self.execute_supabase(
                    lambda: (
                        self.supabase.table("identity_resolution_candidates")
                        .update(payload)
                        .eq("id", existing_id)
                        .execute()
                    ),
                    f"update identity resolution candidate {existing_id}",
                )
                self._increment("identity_observer_candidates_updated")
            else:
                self.execute_supabase(
                    lambda: (
                        self.supabase.table("identity_resolution_candidates")
                        .insert(payload)
                        .execute()
                    ),
                    f"insert identity resolution candidate {candidate_type}",
                )
                self._increment("identity_observer_candidates_inserted")
            self._increment("identity_observer_candidates_recorded")
        except Exception as e:
            logger.warning("Identity observer candidate write failed for %s: %s", politician_id, e)
            self._increment("identity_observer_candidate_write_errors")

    def _record_identity_observer_mapping(
        self, politician_id: str, member_data: dict, person_id: str | None
    ) -> None:
        if not self.identity_observer_loaded or not politician_id or not person_id:
            return
        row = dict(member_data)
        row["id"] = politician_id
        self.identity_resolver.add_existing_identity(
            ExistingIdentity(
                person_id=person_id,
                legacy_politician_id=politician_id,
                deterministic_keys=trusted_external_keys(row),
            )
        )

    def _source_native_legacy_id(self, member_data: dict) -> str | None:
        """Find an existing compatibility profile without ever using a person's name."""
        source_system_key = str(member_data.get("source_system_key") or "").strip()
        source_record_key = str(member_data.get("source_record_key") or "").strip()
        if source_system_key and source_record_key:
            response = self.execute_supabase(
                lambda: (
                    self.supabase.table("source_records")
                    .select("legacy_politician_id")
                    .eq("source_system_key", source_system_key)
                    .eq("source_record_key", source_record_key)
                    .limit(2)
                    .execute()
                ),
                f"resolve source-native legacy profile {source_system_key}:{source_record_key}",
            )
            ids = {
                row.get("legacy_politician_id")
                for row in (response.data or [])
                if row.get("legacy_politician_id")
            }
            if len(ids) == 1:
                return next(iter(ids))

        external_ids = member_data.get("external_ids") or {}
        openstates_id = external_ids.get("openstates")
        if openstates_id:
            response = self.execute_supabase(
                lambda: (
                    self.supabase.table("politicians")
                    .select("id")
                    .contains("external_ids", {"openstates": openstates_id})
                    .limit(2)
                    .execute()
                ),
                f"resolve OpenStates legacy profile {openstates_id}",
            )
            ids = {row.get("id") for row in (response.data or []) if row.get("id")}
            return next(iter(ids)) if len(ids) == 1 else None

        bioguide_id = member_data.get("bioguide_id")
        if bioguide_id:
            response = self.execute_supabase(
                lambda: (
                    self.supabase.table("politicians")
                    .select("id")
                    .eq("bioguide_id", bioguide_id)
                    .limit(2)
                    .execute()
                ),
                f"resolve Bioguide legacy profile {bioguide_id}",
            )
            ids = {row.get("id") for row in (response.data or []) if row.get("id")}
            return next(iter(ids)) if len(ids) == 1 else None

        wikidata_id = external_ids.get("wikidata")
        branch = member_data.get("government_branch")
        if wikidata_id and branch:
            response = self.execute_supabase(
                lambda: (
                    self.supabase.table("politicians")
                    .select("id")
                    .contains("external_ids", {"wikidata": wikidata_id})
                    .eq("government_branch", branch)
                    .limit(2)
                    .execute()
                ),
                f"resolve role-compatible Wikidata legacy profile {wikidata_id}",
            )
            ids = {row.get("id") for row in (response.data or []) if row.get("id")}
            return next(iter(ids)) if len(ids) == 1 else None
        return None

    def _guard_identity_before_hub_write(
        self, member_data: dict, existing_id: str | None
    ) -> IdentityResolution:
        """Block deterministic multi-person conflicts before changing ``politicians``.

        The observer previously ran only after the hub write.  That made its strongest
        outcome (``blocked_conflict``) diagnostic rather than protective: the legacy row
        had already been changed.  Resolve against the start-of-run identity snapshot
        first and fail the record before any update/insert.
        """
        self._ensure_identity_observer_loaded()
        row = dict(member_data)
        deterministic_keys = trusted_external_keys(row)
        if existing_id and deterministic_keys:
            row["id"] = existing_id
        resolution = self.identity_resolver.resolve(packet_from_legacy_politician(row))
        self._increment("identity_observer_packets_checked")
        self._increment(f"identity_observer_{resolution.action}")
        if resolution.action not in ("blocked_conflict", "pending_review"):
            return resolution

        self._increment("identity_prewrite_writes_blocked")
        if resolution.blocked_reason:
            self._increment(f"identity_prewrite_blocked_{resolution.blocked_reason}")
        elif resolution.pending_candidate:
            self._increment(
                f"identity_prewrite_blocked_{resolution.pending_candidate.candidate_type}"
            )
        candidate_legacy_id = existing_id
        if candidate_legacy_id is None and member_data.get("source_system_key"):
            candidate_legacy_id = self._source_native_legacy_id(member_data)
        self.record_identity_resolution_candidate(
            candidate_legacy_id, member_data, resolution
        )
        raise IdentityResolutionConflict(
            "Refusing hub mutation for "
            f"{member_data.get('full_name') or existing_id}: "
            f"{resolution.blocked_reason or 'missing deterministic identity'}"
        )

    def _upsert_source_profile_identity(
        self,
        member_data: dict,
        profile_payload: dict,
    ) -> str:
        """Atomically resolve identity and write hub/source/term data via migration 0022.

        There is intentionally no production fallback to separate table writes. If the
        migration or RPC is missing, this record fails before a partial hub mutation.
        """
        source_system_key = str(member_data.get("source_system_key") or "").strip()
        source_record_key = str(member_data.get("source_record_key") or "").strip()
        if not source_system_key or not source_record_key:
            raise ValueError("source profile packets require source_system_key and source_record_key")

        trusted_ids = [
            {
                "source_system_key": key.source_system_key,
                "external_id_type": key.external_id_type,
                "external_id": key.external_id,
            }
            for key in trusted_external_keys(member_data)
        ]
        classification = normalize_government_classification(member_data)
        location = normalize_location_fields(member_data)
        office_term = {
            "source_term_key": member_data.get("source_term_key") or "current-office",
            "office_title": member_data.get("current_office") or "Public office",
            "role_type": member_data.get("role_type") or "office",
            "organization_name": member_data.get("organization_name"),
            "government_level": classification["government_level"],
            "government_branch": classification["government_branch"],
            "office_type": classification["office_type"],
            "jurisdiction": classification["jurisdiction"],
            "state": location["state"],
            "district": location["district"],
            "term_start": member_data.get("term_start"),
            "term_end": member_data.get("term_end"),
            "term_status": member_data.get("term_status") or "current",
            "metadata": {"source_system_key": source_system_key},
        }
        args = {
            "p_source_system_key": source_system_key,
            "p_source_record_key": source_record_key,
            "p_profile": profile_payload,
            "p_trusted_external_ids": trusted_ids,
            "p_source_url": member_data.get("source_url"),
            "p_raw_payload_ref": member_data.get("raw_payload_ref"),
            "p_payload_hash": member_data.get("payload_hash"),
            "p_verified_lane": member_data.get("verified_lane") or "unverified",
            "p_office_term": office_term,
            "p_source_catalog_slug": member_data.get("source_catalog_slug"),
            "p_source_endpoint_slug": member_data.get("source_endpoint_slug"),
            "p_source_updated_at": member_data.get("source_updated_at"),
        }
        args = _json_compatible(args)
        resp = self.execute_supabase(
            lambda: self.supabase.rpc("upsert_source_profile_identity", args).execute(),
            f"transactional source profile upsert {source_system_key}:{source_record_key}",
        )
        result = (resp.data or [{}])[0]
        politician_id = result.get("legacy_politician_id")
        person_id = result.get("person_id")
        if (
            not politician_id
            or not person_id
            or not result.get("source_record_id")
            or not result.get("office_term_id")
        ):
            raise RuntimeError(
                "upsert_source_profile_identity returned an incomplete identity result"
            )

        self.person_id_by_politician_id[politician_id] = person_id
        action = str(result.get("resolution_action") or "unknown").strip().lower()
        self._increment(f"source_profile_identity_{action}")
        self._increment("hub_rows_upserted")
        self._increment("source_records_upserted")
        self._increment("person_office_terms_upserted")
        self._increment("identity_profiles_synced")
        self._record_identity_observer_mapping(politician_id, member_data, person_id)
        print(f"  [+] Transactionally synced source profile for {member_data['full_name']}")
        return politician_id

    def reconcile_source_snapshot(
        self,
        source_system_key: str,
        seen_record_keys: set[str],
        *,
        record_key_prefix: str | None = None,
    ) -> int:
        """Retire records absent from a complete source snapshot, without deleting identity."""
        if not self.supabase:
            return 0

        seen = {str(value).strip() for value in seen_record_keys if str(value).strip()}
        rows = []
        start = 0
        page_size = 1000
        while True:
            end = start + page_size - 1
            def load_page(start=start, end=end):
                query = (
                    self.supabase.table("source_records")
                    .select("id,source_record_key")
                    .eq("source_system_key", source_system_key)
                    .eq("record_type", "person_profile")
                    .eq("record_status", "active")
                )
                if record_key_prefix:
                    query = query.like("source_record_key", f"{record_key_prefix}%")
                return query.range(start, end).execute()

            resp = self.execute_supabase(
                load_page,
                f"load active {source_system_key} source records for reconciliation",
            )
            batch = resp.data or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
            start += page_size

        missing = [row for row in rows if str(row.get("source_record_key")) not in seen]
        retired_at = datetime.now(timezone.utc).isoformat()
        term_end = date.today().isoformat()
        retired_term_count = 0
        for row in missing:
            source_record_id = row.get("id")
            if not source_record_id:
                continue
            response = self.execute_supabase(
                lambda source_record_id=source_record_id: self.supabase.rpc(
                    "retire_source_profile_record",
                    {
                        "p_source_record_id": source_record_id,
                        "p_retired_at": retired_at,
                        "p_term_end": term_end,
                    },
                ).execute(),
                f"atomically retire absent {source_system_key} source record {source_record_id}",
            )
            result = (response.data or [{}])[0]
            if result.get("record_status") != "retired":
                raise RuntimeError(
                    f"retire_source_profile_record did not retire {source_record_id}"
                )
            retired_term_count += int(result.get("retired_office_term_count") or 0)
        self._increment("source_records_retired", len(missing))
        self._increment("person_office_terms_historicized", retired_term_count)
        return len(missing)

    def upsert_politician(self, member_data: dict):
        """
        Upserts a politician into the Hub table and returns the UUID.

        Matching strategy depends on which stable id the source provides:
          * Federal (bioguide_id present): match bioguide_id, then fall back to
            full_name — the name fallback also migrates legacy rows written before
            bioguide_id was populated.
          * Non-federal with a stable source id (OpenStates ocd-person or Wikidata
            QID in external_ids): match ONLY on that id. State legislators and
            federal exec/judicial officials commonly share names with each other and
            with Congress members, so name matching here would wrongly merge distinct
            people.
          * Otherwise: match on full_name.
        """
        if not self.supabase:
            print(f"  [Dry-run] Upserting politician {member_data['full_name']}")
            return "dummy-uuid"

        bioguide_id = member_data.get("bioguide_id")
        # Stable non-federal identity schemes, most-trusted first. The first one
        # present in external_ids is used for matching (JSONB containment).
        ext = member_data.get("external_ids") or {}
        stable_match = next(
            ((scheme, ext[scheme]) for scheme in _STABLE_SCHEMES if ext.get(scheme)),
            None,
        )

        classification = normalize_government_classification(member_data)
        location = normalize_location_fields(member_data)

        data_to_write = {
            "full_name": member_data.get("full_name"),
            "current_office": member_data.get("current_office"),
            "party": member_data.get("party"),
            # 2-letter USPS state code + district label (both optional; national
            # offices leave them NULL). Powers the directory's location filter.
            "state": location["state"],
            "district": location["district"],
            "government_level": classification["government_level"],
            "government_branch": classification["government_branch"],
            "office_type": classification["office_type"],
            "jurisdiction": classification["jurisdiction"],
            "external_ids": member_data.get("external_ids") or {},
            "aliases": member_data.get("aliases") or [],
            # DEFAULT NOW() only fires on INSERT, so set it explicitly to keep the
            # freshness timestamp accurate when we update existing rows.
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        if bioguide_id:
            data_to_write["bioguide_id"] = bioguide_id

        try:
            if member_data.get("source_system_key") or member_data.get("source_record_key"):
                self._guard_identity_before_hub_write(member_data, None)
                return self._upsert_source_profile_identity(member_data, data_to_write)

            existing_id = None

            if bioguide_id:
                # Federal: bioguide_id column, then name fallback (migrates legacy
                # null-bioguide rows in place).
                resp = self.execute_supabase(
                    lambda: (
                        self.supabase.table("politicians")
                        .select("id")
                        .eq("bioguide_id", bioguide_id)
                        .execute()
                    ),
                    f"select politician by bioguide_id {bioguide_id}",
                )
                if resp.data:
                    existing_id = resp.data[0]["id"]
                if existing_id is None:
                    # Name fallback, but ONLY for legacy federal rows. A row that
                    # carries any non-federal stable identity (OpenStates ocd-person or
                    # Wikidata QID) must never be matched here: a newly-seated federal
                    # member whose bioguide_id isn't in the DB yet would otherwise
                    # overwrite a same-named state legislator or Supreme Court justice,
                    # strip its identity, and corrupt both records.
                    resp = self.execute_supabase(
                        lambda: (
                            self.supabase.table("politicians")
                            .select("id, external_ids")
                            .eq("full_name", member_data["full_name"])
                            .execute()
                        ),
                        f"select federal legacy politician by name {member_data['full_name']}",
                    )
                    for row in (resp.data or []):
                        row_ext = row.get("external_ids") or {}
                        if not any(row_ext.get(scheme) for scheme in _STABLE_SCHEMES):
                            existing_id = row["id"]
                            break
            elif stable_match:
                # Non-federal: match ONLY on the stable id (JSONB containment, served
                # by the external_ids GIN index). No name fallback — see the docstring.
                scheme, value = stable_match
                resp = self.execute_supabase(
                    lambda: (
                        self.supabase.table("politicians")
                        .select("id, bioguide_id")
                        .contains("external_ids", {scheme: value})
                        .execute()
                    ),
                    f"select politician by external id {scheme}",
                )
                # Never adopt a federal congressional row (one carrying a bioguide_id)
                # from a non-federal source. Congress rows store their wikidata QID in
                # external_ids, so a former member now in the exec/judicial set (e.g. a
                # VP who was a senator) would otherwise overwrite the congressional row
                # to executive office — and the two sources would flip-flop it each run.
                for row in (resp.data or []):
                    if not row.get("bioguide_id"):
                        existing_id = row["id"]
                        break
            else:
                resp = self.execute_supabase(
                    lambda: (
                        self.supabase.table("politicians")
                        .select("id")
                        .eq("full_name", member_data["full_name"])
                        .execute()
                    ),
                    f"select politician by name {member_data['full_name']}",
                )
                if resp.data:
                    existing_id = resp.data[0]["id"]

            self._guard_identity_before_hub_write(member_data, existing_id)

            if existing_id is not None:
                self.execute_supabase(
                    lambda: (
                        self.supabase.table("politicians")
                        .update(data_to_write)
                        .eq("id", existing_id)
                        .execute()
                    ),
                    f"update politician {member_data['full_name']}",
                )
                self._increment("hub_rows_updated")
                print(f"  [+] Updated Hub for {member_data['full_name']}")
                person_id = self.sync_legacy_profile_identity(existing_id)
                self._record_identity_observer_mapping(existing_id, member_data, person_id)
                return existing_id

            insert_resp = self.execute_supabase(
                lambda: self.supabase.table("politicians").insert(data_to_write).execute(),
                f"insert politician {member_data['full_name']}",
            )
            if insert_resp.data:
                p_id = insert_resp.data[0]["id"]
                self._increment("hub_rows_inserted")
                print(f"  [+] Inserted new Hub for {member_data['full_name']}")
                person_id = self.sync_legacy_profile_identity(p_id)
                self._record_identity_observer_mapping(p_id, member_data, person_id)
                return p_id
        except Exception as e:
            # Re-raise instead of swallowing. The Hub upsert is the root of every spoke
            # write, so a failure here (e.g. a schema-drift PGRST204 when the live DB is
            # missing a migrated column) must NOT be hidden behind a None return — that
            # let the whole pipeline report success while writing nothing. The per-record
            # try/except in main.py counts the raised error and exits non-zero, which turns
            # a broken run red and blocks the auto-deploy of stale data. See main.py.
            print(f"  [!] Error upserting politician {member_data['full_name']}: {e}")
            raise

        return None

    def sync_legacy_profile_identity(self, politician_id: str):
        """
        Keeps the Phase 1 people/legacy redirect bridge in step with hub writes.

        The RPC is installed by migrations/0011. Missing or drifted schema should fail
        loudly through the preflight, and if it still fails here the whole record should
        error rather than writing a hub row that search/profile cannot resolve canonically.
        """
        if not self.supabase or not politician_id or politician_id == "dummy-uuid":
            return None

        try:
            resp = self.execute_supabase(
                lambda: self.supabase.rpc(
                    "sync_legacy_profile_identity",
                    {"p_politician_id": politician_id},
                ).execute(),
                f"sync canonical identity bridge for {politician_id}",
            )
            if resp.data:
                person_id = resp.data[0].get("person_id")
                self.person_id_by_politician_id[politician_id] = person_id
                self._increment("identity_profiles_synced")
                print("  [+] Synced canonical identity bridge")
                return person_id
        except Exception as e:
            print(f"  [!] Error syncing canonical identity bridge for {politician_id}: {e}")
            raise

        return None

    def _person_id_for_politician(self, politician_id: str):
        if not self.supabase or not politician_id or politician_id == "dummy-uuid":
            return None
        if politician_id not in self.person_id_by_politician_id:
            self.sync_legacy_profile_identity(politician_id)
        return self.person_id_by_politician_id.get(politician_id)

    def _with_person_id(self, politician_id: str, payload: dict) -> dict:
        person_id = self._person_id_for_politician(politician_id)
        if person_id:
            payload["person_id"] = person_id
        return payload

    def upsert_contact_info(self, politician_id: str, contact: dict):
        """
        Upserts official contact info (verified spoke). contact_info.politician_id is
        the primary key, so we conflict-resolve on it.
        """
        if not contact or not any(contact.values()):
            return
        if not self.supabase:
            print(f"  [Dry-run] Upserting contact info for {politician_id}")
            return

        payload = self._with_person_id(
            politician_id,
            {
                "politician_id": politician_id,
                "office_address": contact.get("office_address"),
                "phone_number": contact.get("phone_number"),
                "official_website": contact.get("official_website"),
                # Refresh freshness timestamp on every upsert (DEFAULT NOW() only fires
                # on the initial insert, not on the on-conflict update).
                "last_updated": datetime.now(timezone.utc).isoformat(),
            },
        )
        try:
            self.execute_supabase(
                lambda: self.supabase.table("contact_info").upsert(
                    payload, on_conflict="politician_id"
                ).execute(),
                f"upsert contact info for {politician_id}",
            )
            self._increment("contact_rows_updated")
            print("  [+] Updated contact info")
        except Exception as e:
            print(f"  [!] Error upserting contact info for {politician_id}: {e}")
            raise

    def upsert_financial_disclosures(self, politician_id: str, filings: list):
        """
        Upserts FILING-LEVEL House financial-disclosure records (verified spoke). Each filing
        is one official document (a Periodic Transaction Report or Annual disclosure) linked by
        DocID; the itemized transactions live in the linked PDF, not here (see
        migrations/0005). doc_id is UNIQUE, so we conflict-resolve on it to keep the nightly
        job idempotent.
        """
        if not filings:
            return
        if not self.supabase:
            print(f"  [Dry-run] Upserting {len(filings)} financial disclosures")
            return

        # Dedup on doc_id within the batch: PostgREST rejects a batch that touches the same
        # ON CONFLICT key twice ("cannot affect row a second time").
        person_id = self._person_id_for_politician(politician_id)
        by_doc = {}
        for f in filings:
            doc_id = f.get("doc_id")
            if not doc_id:
                continue
            row = {
                "politician_id": politician_id,
                "filing_type": f.get("filing_type"),
                "filing_date": f.get("filing_date"),
                "doc_id": doc_id,
                "doc_url": f.get("doc_url"),
            }
            if person_id:
                row["person_id"] = person_id
            by_doc[doc_id] = row
        rows = list(by_doc.values())
        if not rows:
            return
        try:
            self.execute_supabase(
                lambda: self.supabase.table("financial_disclosures").upsert(
                    rows, on_conflict="doc_id"
                ).execute(),
                f"upsert {len(rows)} financial disclosures for {politician_id}",
            )
            self._increment("financial_disclosure_filings_written", len(rows))
            print(f"  [+] Upserted {len(rows)} financial disclosures")
        except Exception as e:
            # Re-raise (like upsert_politician) rather than swallowing. This spoke depends on
            # the doc_id/doc_url/filing_type columns from migration 0005; if 0005 isn't applied
            # this fails with PGRST204 for every House member. Swallowing it would let the run
            # exit 0 and deploy with no disclosures written — the exact silent-drift failure
            # this PR exists to eliminate. main.py counts the raised error and exits non-zero.
            print(f"  [!] Error upserting financial disclosures for {politician_id}: {e}")
            raise

    def upsert_campaign_donors(self, politician_id: str, donors: list):
        """
        Upserts verified FEC campaign donors. fec_transaction_id is UNIQUE, so we
        conflict-resolve on it to keep the nightly job idempotent.
        """
        if not donors:
            return
        if not self.supabase:
            print(f"  [Dry-run] Upserting {len(donors)} campaign donors")
            return

        person_id = self._person_id_for_politician(politician_id)
        rows = []
        for d in donors:
            row = {
                "politician_id": politician_id,
                "donor_name": d.get("donor_name"),
                "amount": d.get("amount"),
                "donation_date": d.get("donation_date"),
                "pac_status": d.get("pac_status", False),
                "fec_transaction_id": d.get("fec_transaction_id"),
            }
            if person_id:
                row["person_id"] = person_id
            rows.append(row)
        try:
            self.execute_supabase(
                lambda: self.supabase.table("campaign_donors").upsert(
                    rows, on_conflict="fec_transaction_id"
                ).execute(),
                f"upsert {len(rows)} campaign donors for {politician_id}",
            )
            self._increment("donor_rows_written", len(rows))
            print(f"  [+] Upserted {len(rows)} campaign donors")
        except Exception as e:
            print(f"  [!] Error upserting campaign donors for {politician_id}: {e}")
            raise

    def upsert_voting_records(self, politician_id: str, records: list):
        """
        Upserts verified roll-call votes. The voting_records UNIQUE constraint is
        (politician_id, bill_name, vote_date), so we conflict-resolve on it to keep
        the nightly job idempotent. Callers must dedup rows on that key first.
        """
        if not records:
            return
        if not self.supabase:
            print(f"  [Dry-run] Upserting {len(records)} voting records")
            return

        person_id = self._person_id_for_politician(politician_id)
        rows = []
        for r in records:
            row = {
                "politician_id": politician_id,
                "bill_name": r.get("bill_name"),
                "bill_summary": r.get("bill_summary"),
                "vote_cast": r.get("vote_cast"),
                "vote_date": r.get("vote_date"),
            }
            if person_id:
                row["person_id"] = person_id
            # Stable per-roll-call id + jurisdiction (see migrations/0003). Only added when
            # present, so a row that lacks them leaves the columns untouched on conflict
            # rather than clobbering a previously-stored roll_call_id back to NULL.
            if r.get("roll_call_id") is not None:
                row["roll_call_id"] = r["roll_call_id"]
            if r.get("jurisdiction") is not None:
                row["jurisdiction"] = r["jurisdiction"]
            rows.append(row)

        # Upsert in homogeneous sub-batches grouped by exact key set. PostgREST normalises a
        # mixed batch to the UNION of all keys and writes NULL for any key absent from a
        # given row's DO UPDATE SET — so a batch mixing rows that carry roll_call_id with
        # rows that don't would still null out the latter's stored value. Grouping by key
        # signature guarantees every batch is uniform, so an absent column is genuinely
        # omitted from that batch's UPDATE rather than set to NULL.
        groups: dict = defaultdict(list)
        for row in rows:
            groups[frozenset(row.keys())].append(row)

        # Each group upserts independently so a failure in one (e.g. a transient error on
        # the id-less group) doesn't silently skip the others.
        upserted = 0
        for group in groups.values():
            try:
                self.execute_supabase(
                    lambda group=group: self.supabase.table("voting_records").upsert(
                        group, on_conflict="politician_id,bill_name,vote_date"
                    ).execute(),
                    f"upsert {len(group)} voting records for {politician_id}",
                )
                upserted += len(group)
                self._increment("voting_rows_written", len(group))
            except Exception as e:
                print(f"  [!] Error upserting {len(group)} voting records for {politician_id}: {e}")
                raise
        if upserted:
            print(f"  [+] Upserted {upserted} voting records")

    def upsert_relationships(self, politician_id: str, edges: list):
        """
        Upserts structured network ties (e.g. LittleSis board/affiliation edges) for a
        politician. UNIQUE(politician_id, related_name, relationship_type) keeps the
        nightly job idempotent.

        related_politician_id is resolved here by an EXACT full_name match to a tracked
        politician (never fuzzy — the loader's identity rule, same as upsert_politician).
        When the related entity isn't someone we track, it stays NULL and the frontend
        renders an external link instead of an internal profile link.
        """
        if not edges:
            return
        if not self.supabase:
            print(f"  [Dry-run] Upserting {len(edges)} relationships")
            return

        names = {e.get("related_name") for e in edges if e.get("related_name")}
        if not names:
            return
        # Resolve every related name in one query. A query failure raises before any
        # relationship upsert, so existing internal links cannot be nulled by a partial run.
        name_to_id, resolution_counts = self._resolve_exact_names_with_outcomes(names)

        person_id = self._person_id_for_politician(politician_id)
        rows = []
        for e in edges:
            related_name = e.get("related_name")
            if not related_name:
                continue
            row = {
                "politician_id": politician_id,
                "related_name": related_name,
                # Never NULL: relationship_type is part of the UNIQUE/ON CONFLICT key, and
                # a NULL would break upsert idempotency (NULL <> NULL in Postgres).
                "relationship_type": e.get("relationship_type") or "Connection",
                "source_api": e.get("source_api", "LittleSis"),
                "url": e.get("url"),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            if person_id:
                row["person_id"] = person_id
            row["related_politician_id"] = name_to_id.get(related_name)
            rows.append(row)
        try:
            self.execute_supabase(
                lambda: self.supabase.table("relationships").upsert(
                    rows, on_conflict="politician_id,related_name,relationship_type"
                ).execute(),
                f"upsert {len(rows)} relationships for {politician_id}",
            )
            self._increment("relationship_rows_written", len(rows))
            for outcome, count in resolution_counts.items():
                self._increment(f"relationship_target_names_{outcome}", count)
            print(f"  [+] Upserted {len(rows)} relationships")
        except Exception as e:
            print(f"  [!] Error upserting relationships for {politician_id}: {e}")
            raise

    def _resolve_exact_names(self, names):
        """
        Map each name in `names` to the politician id whose full_name EXACTLY matches it,
        in a single query. Deliberately exact-only (no fuzzy) per the entity-resolution
        rule; a name that matches zero or MORE THAN ONE politician is omitted (resolves to
        None at the call site) rather than guessing.

        Returns a dict on success (possibly empty — ran fine, no matches). Query failures
        raise so callers cannot overwrite previously-resolved links with unresolved rows.
        """
        return self._resolve_exact_names_with_outcomes(names)[0]

    def _resolve_exact_names_with_outcomes(self, names):
        """Resolve exact relationship targets and report non-identifying outcomes.

        ``not_tracked`` deliberately includes external entities. It is an aggregate
        data-quality signal, not a reason to create an identity candidate or make a
        fuzzy relationship link.
        """
        name_list = [n for n in names if n]
        if not self.supabase or not name_list:
            return {}, {
                "queried": 0,
                "resolved_exact": 0,
                "not_tracked": 0,
                "ambiguous": 0,
            }
        try:
            resp = self.execute_supabase(
                lambda: (
                    self.supabase.table("politicians")
                    .select("id, full_name")
                    .in_("full_name", name_list)
                    .execute()
                ),
                f"resolve {len(name_list)} politician names",
            )
        except Exception as e:
            # A failed resolve aborts the relationship write so valid internal links are
            # never replaced by unresolved/null values.
            logger.warning("Bulk name resolve failed for %d names: %s", len(name_list), e)
            raise

        # Count matches per name so ambiguous names (>1 politician) are dropped.
        ids_by_name: dict[str, list] = {}
        for row in (resp.data or []):
            ids_by_name.setdefault(row["full_name"], []).append(row["id"])
        resolved = {}
        not_tracked = 0
        ambiguous = 0
        for name in name_list:
            ids = ids_by_name.get(name, [])
            if len(ids) == 1:
                resolved[name] = ids[0]
            elif ids:
                ambiguous += 1
            else:
                not_tracked += 1
        return resolved, {
            "queried": len(name_list),
            "resolved_exact": len(resolved),
            "not_tracked": not_tracked,
            "ambiguous": ambiguous,
        }

    def process_mentions(self, politician_id: str, data_list: list, source_api: str):
        """
        Takes third party data and links it to the politician as an unconfirmed mention.
        """
        if not data_list:
            return

        if not self.supabase:
            print(f"  [Dry-run] Inserted {len(data_list)} mentions from {source_api}")
            return

        person_id = self._person_id_for_politician(politician_id)
        inserted_count = 0
        for item in data_list:
            # NewsAggregator returns provider-specific provenance per item. Preserve it
            # in the existing source_api column instead of flattening every provider to
            # the generic aggregator label. Other callers keep their explicit fallback.
            item_source_api = item.get("source_api") or source_api
            mention_data = {
                "politician_id": politician_id,
                "source_api": item_source_api,
                "content_summary": item.get("content_summary", ""),
                "url": item.get("url"),
                "sentiment_score": item.get("sentiment_score"),
            }
            if person_id:
                mention_data["person_id"] = person_id
            try:
                self.execute_supabase(
                    lambda mention_data=mention_data: (
                        self.supabase.table("unconfirmed_mentions").insert(mention_data).execute()
                    ),
                    f"insert {item_source_api} mention for {politician_id}",
                )
                inserted_count += 1
            except Exception as e:
                if self._is_non_retryable_supabase_error(e):
                    self._increment("media_mentions_duplicates")
                    logger.debug(
                        "Duplicate mention from %s (%s): %s",
                        item_source_api,
                        item.get("url"),
                        e,
                    )
                    continue
                print(
                    f"  [!] Error inserting {item_source_api} mention for "
                    f"{politician_id}: {e}"
                )
                raise

        self._increment("media_mentions_inserted", inserted_count)
        print(f"  [+] Added {inserted_count} new mentions from {source_api}")
