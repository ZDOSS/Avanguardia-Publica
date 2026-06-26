from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


MIGRATION_HELP = (
    "Supabase schema preflight failed. Apply schema.sql and migrations/*.sql manually "
    "in the Supabase SQL editor, in order, then re-run the scraper. See README "
    '"Applying migrations".'
)

NIL_UUID = "00000000-0000-0000-0000-000000000000"


@dataclass(frozen=True)
class TableRequirement:
    table: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class RpcRequirement:
    name: str
    args: dict


TABLE_REQUIREMENTS: tuple[TableRequirement, ...] = (
    TableRequirement(
        "politicians",
        ("id", "state", "district", "external_ids"),
    ),
    TableRequirement(
        "contact_info",
        (
            "politician_id",
            "office_address",
            "phone_number",
            "official_website",
            "last_updated",
        ),
    ),
    TableRequirement(
        "campaign_donors",
        (
            "id",
            "politician_id",
            "donor_name",
            "amount",
            "donation_date",
            "pac_status",
            "fec_transaction_id",
        ),
    ),
    TableRequirement(
        "voting_records",
        ("id", "roll_call_id", "jurisdiction"),
    ),
    TableRequirement(
        "unconfirmed_mentions",
        (
            "id",
            "politician_id",
            "source_api",
            "content_summary",
            "sentiment_score",
            "url",
        ),
    ),
    TableRequirement(
        "relationships",
        (
            "id",
            "politician_id",
            "related_name",
            "related_politician_id",
            "relationship_type",
            "source_api",
            "url",
            "last_updated",
        ),
    ),
    TableRequirement(
        "financial_disclosures",
        ("id", "doc_id", "doc_url", "filing_type"),
    ),
)

RPC_REQUIREMENTS: tuple[RpcRequirement, ...] = (
    RpcRequirement("get_shared_donors", {"p_id": NIL_UUID}),
    RpcRequirement("get_covoting", {"p_id": NIL_UUID}),
    RpcRequirement("get_network_ties", {"p_id": NIL_UUID}),
)


class SchemaPreflightError(RuntimeError):
    """Raised when the live Supabase schema does not match scraper expectations."""

    def __init__(self, failures: Iterable[str]):
        self.failures = tuple(failures)
        details = "\n".join(f"  - {failure}" for failure in self.failures)
        super().__init__(f"{MIGRATION_HELP}\nMissing or inaccessible requirements:\n{details}")


def run_schema_preflight(supabase) -> None:
    """
    Verify the live Supabase API exposes the schema this scraper writes to.

    The project does not have a migration runner in CI. These checks deliberately use
    the same PostgREST surface as the loader so schema-cache drift, missing columns,
    missing tables, missing RPC functions, or missing grants fail before any extractor
    spends quota or starts a partial run.
    """
    if supabase is None:
        print("Schema preflight skipped in dry-run mode.")
        return

    failures: list[str] = []
    for requirement in TABLE_REQUIREMENTS:
        try:
            (
                supabase.table(requirement.table)
                .select(",".join(requirement.columns))
                .limit(0)
                .execute()
            )
        except Exception as exc:  # pragma: no cover - exact supabase errors vary.
            failures.append(
                f"{requirement.table} columns [{', '.join(requirement.columns)}]: {exc}"
            )

    for requirement in RPC_REQUIREMENTS:
        try:
            supabase.rpc(requirement.name, requirement.args).execute()
        except Exception as exc:  # pragma: no cover - exact supabase errors vary.
            failures.append(f"RPC {requirement.name}({', '.join(requirement.args)}): {exc}")

    if failures:
        raise SchemaPreflightError(failures)

    print(
        "Schema preflight passed "
        f"({len(TABLE_REQUIREMENTS)} table checks, {len(RPC_REQUIREMENTS)} RPC checks)."
    )
