"""phase 5 country/jurisdiction abstraction layer

Adds ``country_code`` (ISO 3166-1 alpha-2) and ``jurisdiction_level``
(federal/state/provincial/territorial) to the ``politician`` table.
Existing US federal rows are backfilled with ``country_code = 'US'`` and
``jurisdiction_level = 'federal'`` so the new columns can be NOT NULL
without breaking the unique source dedup constraint.

The new fields are indexed to keep country-scoped and state-scoped
listings cheap as the table grows.

Revision ID: f7c2a1d4b3e5
Revises: d4a8f3b1c9e2
Create Date: 2026-06-09 08:00:00.000000
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "f7c2a1d4b3e5"
down_revision: str | None = "d4a8f3b1c9e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add as nullable first so the ALTER TABLE itself doesn't fail on
    # populated tables; backfill in the same migration, then enforce
    # NOT NULL once every existing row has a value.
    op.add_column(
        "politician",
        sa.Column("country_code", sa.String(length=2), nullable=True),
    )
    op.add_column(
        "politician",
        sa.Column("jurisdiction_level", sa.String(length=20), nullable=True),
    )

    # Every row inserted before this migration is a US federal legislator
    # (the Phase 1-4 ETL only ingested Congress.gov / FEC / VoteView).
    op.execute(
        "UPDATE politician SET country_code = 'US', "
        "jurisdiction_level = 'federal' "
        "WHERE country_code IS NULL OR jurisdiction_level IS NULL"
    )

    op.alter_column("politician", "country_code", nullable=False)
    op.alter_column("politician", "jurisdiction_level", nullable=False)

    op.create_index(
        "ix_politician_country_code",
        "politician",
        ["country_code"],
    )
    op.create_index(
        "ix_politician_jurisdiction",
        "politician",
        ["country_code", "jurisdiction_level", "state"],
    )


def downgrade() -> None:
    op.drop_index("ix_politician_jurisdiction", table_name="politician")
    op.drop_index("ix_politician_country_code", table_name="politician")
    op.drop_column("politician", "jurisdiction_level")
    op.drop_column("politician", "country_code")
