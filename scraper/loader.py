import logging
from datetime import datetime, timezone
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Stable, non-federal identity schemes carried in external_ids, most-trusted first.
# A row carrying any of these is owned by a non-federal source (state legislators via
# OpenStates, federal exec/judicial via Wikidata) and must never be matched by the
# federal bioguide name-fallback. Single source of truth so the match logic and the
# fallback guard can never drift apart.
_STABLE_SCHEMES = ("openstates", "wikidata")


class SupabaseLoader:
    def __init__(self, url: str, key: str):
        if url and key:
            self.supabase: Client = create_client(url, key)
            print("Supabase client initialized.")
        else:
            self.supabase = None
            print("Warning: SUPABASE_URL or SUPABASE_KEY is not set. Running in dry-run mode.")

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

        data_to_write = {
            "full_name": member_data.get("full_name"),
            "current_office": member_data.get("current_office"),
            "party": member_data.get("party"),
            # 2-letter USPS state code + district label (both optional; national
            # offices leave them NULL). Powers the directory's location filter.
            "state": member_data.get("state"),
            "district": member_data.get("district"),
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
                resp = (
                    self.supabase.table("politicians")
                    .select("id")
                    .eq("bioguide_id", bioguide_id)
                    .execute()
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
                    resp = (
                        self.supabase.table("politicians")
                        .select("id, external_ids")
                        .eq("full_name", member_data["full_name"])
                        .execute()
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
                resp = (
                    self.supabase.table("politicians")
                    .select("id, bioguide_id")
                    .contains("external_ids", {scheme: value})
                    .execute()
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
                resp = (
                    self.supabase.table("politicians")
                    .select("id")
                    .eq("full_name", member_data["full_name"])
                    .execute()
                )
                if resp.data:
                    existing_id = resp.data[0]["id"]

            if existing_id is not None:
                self.supabase.table("politicians").update(data_to_write).eq("id", existing_id).execute()
                print(f"  [+] Updated Hub for {member_data['full_name']}")
                return existing_id

            insert_resp = self.supabase.table("politicians").insert(data_to_write).execute()
            if insert_resp.data:
                p_id = insert_resp.data[0]["id"]
                print(f"  [+] Inserted new Hub for {member_data['full_name']}")
                return p_id
        except Exception as e:
            print(f"  [!] Error upserting politician {member_data['full_name']}: {e}")

        return None

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

        payload = {
            "politician_id": politician_id,
            "office_address": contact.get("office_address"),
            "phone_number": contact.get("phone_number"),
            "official_website": contact.get("official_website"),
            # Refresh freshness timestamp on every upsert (DEFAULT NOW() only fires
            # on the initial insert, not on the on-conflict update).
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.supabase.table("contact_info").upsert(
                payload, on_conflict="politician_id"
            ).execute()
            print("  [+] Updated contact info")
        except Exception as e:
            print(f"  [!] Error upserting contact info for {politician_id}: {e}")

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

        rows = [
            {
                "politician_id": politician_id,
                "donor_name": d.get("donor_name"),
                "amount": d.get("amount"),
                "donation_date": d.get("donation_date"),
                "pac_status": d.get("pac_status", False),
                "fec_transaction_id": d.get("fec_transaction_id"),
            }
            for d in donors
        ]
        try:
            self.supabase.table("campaign_donors").upsert(
                rows, on_conflict="fec_transaction_id"
            ).execute()
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

        rows = [
            {
                "politician_id": politician_id,
                "bill_name": r.get("bill_name"),
                "bill_summary": r.get("bill_summary"),
                "vote_cast": r.get("vote_cast"),
                "vote_date": r.get("vote_date"),
                # Stable per-roll-call id + jurisdiction (see migrations/0003). Both
                # optional — older extractor output without them upserts as NULL.
                "roll_call_id": r.get("roll_call_id"),
                "jurisdiction": r.get("jurisdiction"),
            }
            for r in records
        ]
        try:
            self.supabase.table("voting_records").upsert(
                rows, on_conflict="politician_id,bill_name,vote_date"
            ).execute()
            print(f"  [+] Upserted {len(rows)} voting records")
        except Exception as e:
            print(f"  [!] Error upserting voting records for {politician_id}: {e}")

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

        rows = []
        for e in edges:
            related_name = e.get("related_name")
            if not related_name:
                continue
            rows.append({
                "politician_id": politician_id,
                "related_name": related_name,
                "related_politician_id": self._resolve_exact_name(related_name),
                "relationship_type": e.get("relationship_type"),
                "source_api": e.get("source_api", "LittleSis"),
                "url": e.get("url"),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            })
        if not rows:
            return
        try:
            self.supabase.table("relationships").upsert(
                rows, on_conflict="politician_id,related_name,relationship_type"
            ).execute()
            print(f"  [+] Upserted {len(rows)} relationships")
        except Exception as e:
            print(f"  [!] Error upserting relationships for {politician_id}: {e}")

    def _resolve_exact_name(self, name: str):
        """
        Return the politician id whose full_name is an EXACT match to `name`, or None.
        Deliberately exact-only (no fuzzy) per the entity-resolution rule; an ambiguous
        or absent match resolves to None rather than guessing.
        """
        if not self.supabase or not name:
            return None
        try:
            resp = (
                self.supabase.table("politicians")
                .select("id")
                .eq("full_name", name)
                .execute()
            )
            if resp.data and len(resp.data) == 1:
                return resp.data[0]["id"]
        except Exception as e:
            logger.debug("Name resolve failed for %r: %s", name, e)
        return None

    def process_mentions(self, politician_id: str, data_list: list, source_api: str):
        """
        Takes third party data and links it to the politician as an unconfirmed mention.
        """
        if not data_list:
            return

        if not self.supabase:
            print(f"  [Dry-run] Inserted {len(data_list)} mentions from {source_api}")
            return

        inserted_count = 0
        for item in data_list:
            mention_data = {
                "politician_id": politician_id,
                "source_api": source_api,
                "content_summary": item.get("content_summary", ""),
                "url": item.get("url"),
                "sentiment_score": item.get("sentiment_score"),
            }
            try:
                self.supabase.table("unconfirmed_mentions").insert(mention_data).execute()
                inserted_count += 1
            except Exception as e:
                # Most commonly a UNIQUE(politician_id, source_api, url) violation on a
                # mention we already stored — expected, so we keep going. Log at debug so
                # genuine failures (schema/permission errors) are still discoverable.
                logger.debug("Skipped mention from %s (%s): %s", source_api, item.get("url"), e)

        print(f"  [+] Added {inserted_count} new mentions from {source_api}")
