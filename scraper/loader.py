import logging
from datetime import datetime, timezone
from supabase import create_client, Client

logger = logging.getLogger(__name__)


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

        Matching strategy (most-stable first):
          1. bioguide_id  — the canonical key from @unitedstates/congress-legislators.
          2. full_name    — fallback that also migrates legacy rows written before
                            bioguide_id was populated, so we update them in place
                            instead of creating duplicates.
        """
        if not self.supabase:
            print(f"  [Dry-run] Upserting politician {member_data['full_name']}")
            return "dummy-uuid"

        bioguide_id = member_data.get("bioguide_id")

        data_to_write = {
            "full_name": member_data.get("full_name"),
            "current_office": member_data.get("current_office"),
            "party": member_data.get("party"),
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

            # 1. Match on the stable canonical key.
            if bioguide_id:
                resp = (
                    self.supabase.table("politicians")
                    .select("id")
                    .eq("bioguide_id", bioguide_id)
                    .execute()
                )
                if resp.data:
                    existing_id = resp.data[0]["id"]

            # 2. Fallback: match on name (covers legacy rows with a NULL bioguide_id).
            if existing_id is None:
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
