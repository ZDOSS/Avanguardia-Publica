"""VoteView bulk importer for voting records and DW-NOMINATE ideology scores.

VoteView provides:
- Roll call votes CSV (icpsr, rollnumber, cast_code, congress, chamber, date, ...)
- Ideology scores CSV (icpsr, dim1, dim2, congress, chamber)

Sources: https://voteview.com/articles/data_help
"""

import io
from typing import Any

import httpx
import pandas as pd

from app.etl.base import BaseSourceAdapter


class VoteViewAdapter(BaseSourceAdapter):
    """Bulk importer for VoteView roll call votes and ideology scores."""

    source_name = "voteview"
    base_url = "https://voteview.com/static/data/out"
    max_pages_default = 1  # bulk download, not paginated

    # VoteView CSV URLs for current congress + historical
    # VoteView prefixes congress-specific files with the chamber code "HS"
    # (House + Senate combined). e.g. HS118_votes.csv, HS118_members.csv.
    VOTES_URL = f"{base_url}/votes/" + "HS{congress}_votes.csv"
    MEMBERS_URL = f"{base_url}/members/" + "HS{congress}_members.csv"

    async def fetch_records(self, congress: int | None = None) -> list[dict[str, Any]]:
        """Fetch VoteView data for a given congress (or all if None)."""
        records = []
        # If no congress specified, fetch current (118th) and recent (117th, 116th)
        target_congresses = [congress] if congress else [118, 117, 116]

        async with httpx.AsyncClient() as client:
            for c in target_congresses:
                # Fetch member ideology scores
                members_url = self.MEMBERS_URL.format(congress=c)
                try:
                    resp = await client.get(members_url, timeout=60)
                    resp.raise_for_status()
                    members_df = pd.read_csv(io.StringIO(resp.text))
                    for _, row in members_df.iterrows():
                        raw_icpsr = row.get("icpsr")
                        raw_chamber = row.get("chamber")
                        records.append({
                            "_type": "ideology_score",
                            "congress": c,
                            "icpsr": str(raw_icpsr).strip() if raw_icpsr is not None and not pd.isna(raw_icpsr) else "",
                            "chamber": str(raw_chamber).strip().lower() if raw_chamber is not None and not pd.isna(raw_chamber) else "",
                            "dim1": row.get("nominate_dim1") if pd.notna(row.get("nominate_dim1")) else None,
                            "dim2": row.get("nominate_dim2") if pd.notna(row.get("nominate_dim2")) else None,
                        })
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        continue  # skip unavailable congresses
                    raise

                # Fetch roll call votes
                votes_url = self.VOTES_URL.format(congress=c)
                try:
                    resp = await client.get(votes_url, timeout=60)
                    resp.raise_for_status()
                    votes_df = pd.read_csv(io.StringIO(resp.text))
                    for _, row in votes_df.iterrows():
                        raw_icpsr = row.get("icpsr")
                        raw_chamber = row.get("chamber")
                        records.append({
                            "_type": "voting_record",
                            "congress": c,
                            "icpsr": str(raw_icpsr).strip() if raw_icpsr is not None and not pd.isna(raw_icpsr) else "",
                            "chamber": str(raw_chamber).strip().lower() if raw_chamber is not None and not pd.isna(raw_chamber) else "",
                            "rollnumber": int(row.get("rollnumber", 0)) if pd.notna(row.get("rollnumber")) else 0,
                            "session": int(row.get("session", 0)) if pd.notna(row.get("session")) else 1,
                            "cast_code": int(row.get("cast_code", 0)) if pd.notna(row.get("cast_code")) else 0,
                            "bill_number": str(row.get("bill_number", "")).strip() if pd.notna(row.get("bill_number")) else None,
                            "bill_type": str(row.get("bill_type", "")).strip() if pd.notna(row.get("bill_type")) else None,
                            "vote_date": (
                                f"{int(row.get('date')):08d}"[:4]
                                + "-"
                                + f"{int(row.get('date')):08d}"[4:6]
                                + "-"
                                + f"{int(row.get('date')):08d}"[6:]
                            ) if pd.notna(row.get("date")) else None,
                            "issue_area": str(row.get("issue_area", "")).strip() if pd.notna(row.get("issue_area")) else None,
                        })
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        continue
                    raise
        return records

    def normalize(self, raw: dict) -> dict[str, Any]:
        """Map VoteView raw record to unified model."""
        record_type = raw.get("_type")
        if record_type == "ideology_score":
            return self._normalize_ideology(raw)
        elif record_type == "voting_record":
            return self._normalize_vote(raw)
        return {}

    def _normalize_ideology(self, raw: dict) -> dict[str, Any]:
        # Construct source_record_id: voteview-{congress}-{icpsr}
        source_record_id = f"voteview-{raw['congress']}-{raw['icpsr']}"
        return {
            "_model": "PoliticianIdeologyScore",
            "congress": raw["congress"],
            "chamber": raw["chamber"],
            "dw_nominate_dim1": raw.get("dim1"),
            "dw_nominate_dim2": raw.get("dim2"),
            "source_name": self.source_name,
            "source_record_id": source_record_id,
            "_icpsr": raw["icpsr"],
        }

    def _normalize_vote(self, raw: dict) -> dict[str, Any]:
        # VoteView cast_code: 1=yea, 2=paired yea, 3=announced yea, 4=announced nay,
        # 5=paired nay, 6=nay, 7=present (rules violation), 8=present (rules violation),
        # 9=not voting, 0=present
        cast_code = raw.get("cast_code", 0)
        vote_map = {
            1: "yea", 2: "yea", 3: "yea",
            4: "nay", 5: "nay", 6: "nay",
            7: "present", 8: "present", 0: "present",
            9: "not_voting",
        }
        vote = vote_map.get(cast_code, "unknown")

        # Construct source_record_id: voteview-{congress}-{session}-{rollnumber}-{icpsr}
        source_record_id = (
            f"voteview-{raw['congress']}-{raw['session']}-{raw['rollnumber']}-{raw['icpsr']}"
        )

        return {
            "_model": "VotingRecord",
            "roll_call_number": raw["rollnumber"],
            "congress": raw["congress"],
            "session": raw["session"],
            "chamber": raw["chamber"],
            "bill_number": raw.get("bill_number"),
            "bill_type": raw.get("bill_type"),
            "vote": vote,
            "vote_date": raw.get("vote_date"),
            "issue_area": raw.get("issue_area"),
            "source_name": self.source_name,
            "source_record_id": source_record_id,
            "_icpsr": raw["icpsr"],
        }

    async def _upsert(self, record: dict, db=None) -> None:
        """Insert or update a normalized VoteView record."""
        from app.models import Politician, PoliticianIdeologyScore, VotingRecord

        # Resolve politician by icpsr_id
        icpsr = record.pop("_icpsr", None)
        if not icpsr:
            return

        politician = db.query(Politician).filter(Politician.icpsr_id == icpsr).first()
        if not politician:
            return  # skip unmatched records

        record["politician_id"] = politician.id
        model_name = record.pop("_model")

        if model_name == "VotingRecord":
            existing = db.query(VotingRecord).filter(
                VotingRecord.source_name == record["source_name"],
                VotingRecord.source_record_id == record["source_record_id"],
            ).first()
            if existing:
                for k, v in record.items():
                    setattr(existing, k, v)
            else:
                db.add(VotingRecord(**record))

        elif model_name == "PoliticianIdeologyScore":
            # Upsert by source_name + source_record_id
            existing = db.query(PoliticianIdeologyScore).filter(
                PoliticianIdeologyScore.source_name == record["source_name"],
                PoliticianIdeologyScore.source_record_id == record["source_record_id"],
            ).first()
            if existing:
                for k, v in record.items():
                    setattr(existing, k, v)
            else:
                db.add(PoliticianIdeologyScore(**record))
