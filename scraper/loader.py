import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from supabase import create_client, Client

from government_classification import normalize_government_classification, normalize_location_fields

logger = logging.getLogger(__name__)

# Stable, non-federal identity schemes carried in external_ids, most-trusted first.
# A row carrying any of these is owned by a non-federal source (state legislators via
# OpenStates, federal exec/judicial via Wikidata) and must never be matched by the
# federal bioguide name-fallback. Single source of truth so the match logic and the
# fallback guard can never drift apart.
_STABLE_SCHEMES = ("openstates", "wikidata")


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
                self.sync_legacy_profile_identity(existing_id)
                return existing_id

            insert_resp = self.execute_supabase(
                lambda: self.supabase.table("politicians").insert(data_to_write).execute(),
                f"insert politician {member_data['full_name']}",
            )
            if insert_resp.data:
                p_id = insert_resp.data[0]["id"]
                self._increment("hub_rows_inserted")
                print(f"  [+] Inserted new Hub for {member_data['full_name']}")
                self.sync_legacy_profile_identity(p_id)
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
            except Exception as e:
                print(f"  [!] Error upserting {len(group)} voting records for {politician_id}: {e}")
        if upserted:
            self._increment("voting_rows_written", upserted)
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
        # Resolve every related name to an internal id in ONE query, not one per edge.
        # None signals the resolve query FAILED (vs an empty dict = ran fine, no matches).
        name_to_id = self._resolve_exact_names(names)
        # On a resolve failure we must NOT write related_politician_id: doing so would set
        # it NULL for every existing tie and clobber valid internal profile links until the
        # next clean run. Omitting the key leaves the column untouched on conflict (the
        # presence is uniform across all rows, so PostgREST won't union-NULL it either).
        resolved = name_to_id is not None

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
            if resolved:
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
            print(f"  [+] Upserted {len(rows)} relationships")
        except Exception as e:
            print(f"  [!] Error upserting relationships for {politician_id}: {e}")

    def _resolve_exact_names(self, names):
        """
        Map each name in `names` to the politician id whose full_name EXACTLY matches it,
        in a single query. Deliberately exact-only (no fuzzy) per the entity-resolution
        rule; a name that matches zero or MORE THAN ONE politician is omitted (resolves to
        None at the call site) rather than guessing.

        Returns a dict on success (possibly empty — ran fine, no matches), or None if the
        query FAILED. Callers must treat None differently from {}: a failure must not be
        read as "nothing matched" and used to overwrite previously-resolved links.
        """
        name_list = [n for n in names if n]
        if not self.supabase or not name_list:
            return {}
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
            # WARNING, not DEBUG: a resolve failure means this run skips internal-link
            # resolution for these relationships (to avoid clobbering existing links), so
            # it should be visible in production logs rather than silently swallowed.
            logger.warning("Bulk name resolve failed for %d names: %s", len(name_list), e)
            return None

        # Count matches per name so ambiguous names (>1 politician) are dropped.
        ids_by_name: dict[str, list] = {}
        for row in (resp.data or []):
            ids_by_name.setdefault(row["full_name"], []).append(row["id"])
        return {name: ids[0] for name, ids in ids_by_name.items() if len(ids) == 1}

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
            mention_data = {
                "politician_id": politician_id,
                "source_api": source_api,
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
                    f"insert {source_api} mention for {politician_id}",
                )
                inserted_count += 1
            except Exception as e:
                # Most commonly a UNIQUE(politician_id, source_api, url) violation on a
                # mention we already stored — expected, so we keep going. Log at debug so
                # genuine failures (schema/permission errors) are still discoverable.
                logger.debug("Skipped mention from %s (%s): %s", source_api, item.get("url"), e)

        self._increment("media_mentions_inserted", inserted_count)
        print(f"  [+] Added {inserted_count} new mentions from {source_api}")
