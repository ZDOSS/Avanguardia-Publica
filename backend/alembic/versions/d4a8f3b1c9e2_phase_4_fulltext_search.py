"""phase 4 full-text search: tsvector columns + GIN indexes

Adds a generated ``search_tsv`` column on politician, organization,
contribution, and voting_record, backed by a GIN index for fast
``to_tsquery`` lookups. The columns are populated from existing text
fields and updated automatically on INSERT/UPDATE — no application-side
trigger maintenance required.

Revision ID: d4a8f3b1c9e2
Revises: 5b8e498be220
Create Date: 2026-06-08 23:30:00.000000
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "d4a8f3b1c9e2"
down_revision: str | None = "5b8e498be220"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Politician: full_name is the primary match field, with bio_text as
    # secondary content. Weights A/B put name matches ahead of bio.
    op.execute(
        """
        ALTER TABLE politician
        ADD COLUMN search_tsv tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(full_name, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(bio_text, '')), 'B')
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_politician_search_tsv ON politician USING GIN (search_tsv)")

    # Organization: name only.
    op.execute(
        """
        ALTER TABLE organization
        ADD COLUMN search_tsv tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(name, ''))
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_organization_search_tsv ON organization USING GIN (search_tsv)")

    # Contribution: donor_name + recipient_name + employer/occupation.
    op.execute(
        """
        ALTER TABLE contribution
        ADD COLUMN search_tsv tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(donor_name, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(recipient_name, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(employer, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(occupation, '')), 'B')
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_contribution_search_tsv ON contribution USING GIN (search_tsv)")

    # Voting record: bill_title is the natural search target.
    op.execute(
        """
        ALTER TABLE voting_record
        ADD COLUMN search_tsv tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(bill_title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(issue_area, '')), 'B')
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_voting_record_search_tsv ON voting_record USING GIN (search_tsv)")

    # politician_tag junction table for admin-defined tags. Lives in the
    # same migration as search because both are Phase 4 features; splitting
    # them would require an extra down_revision for no real benefit.
    op.create_table(
        "politician_tag",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("politician_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["politician_id"], ["politician.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("politician_id", "tag_id", name="uq_politician_tag"),
    )


def downgrade() -> None:
    op.drop_table("politician_tag")

    op.execute("DROP INDEX IF EXISTS ix_voting_record_search_tsv")
    op.execute("ALTER TABLE voting_record DROP COLUMN IF EXISTS search_tsv")

    op.execute("DROP INDEX IF EXISTS ix_contribution_search_tsv")
    op.execute("ALTER TABLE contribution DROP COLUMN IF EXISTS search_tsv")

    op.execute("DROP INDEX IF EXISTS ix_organization_search_tsv")
    op.execute("ALTER TABLE organization DROP COLUMN IF EXISTS search_tsv")

    op.execute("DROP INDEX IF EXISTS ix_politician_search_tsv")
    op.execute("ALTER TABLE politician DROP COLUMN IF EXISTS search_tsv")
