"""phase 2 data richness schema additions

Adds columns/constraints that were originally added in-place to the initial
schema migration. Alembic would treat those in-place edits as already
applied on any environment that ran Phase 1, so the new columns were never
created. This migration brings those environments up to the Phase 2 schema
without re-creating any of the 13 original tables.

Pre-existing rows in ``organization`` and ``politician_ideology_score`` are
backfilled with deterministic per-row ``source_record_id`` values
(``legacy-org-{id}`` / ``legacy-ideology-{id}``) so that the new
``uq_organization_dedup`` / ``uq_ideology_score_dedup`` unique constraints
can be created without colliding on a shared empty default.

Revision ID: c3e61c962fc7
Revises: a7b4496a01ea
Create Date: 2026-06-08 23:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3e61c962fc7"
down_revision: Union[str, None] = "a7b4496a01ea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "contribution",
        sa.Column("politician_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_contribution_politician_id",
        "contribution",
        "politician",
        ["politician_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # organization: add nullable columns, backfill pre-existing rows, then
    # enforce NOT NULL + UNIQUE.
    op.add_column(
        "organization",
        sa.Column("source_name", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "organization",
        sa.Column("source_record_id", sa.String(length=100), nullable=True),
    )
    op.execute(
        "UPDATE organization SET source_name = 'legacy', "
        "source_record_id = 'legacy-org-' || id "
        "WHERE source_name IS NULL OR source_record_id IS NULL"
    )
    op.alter_column("organization", "source_name", nullable=False)
    op.alter_column("organization", "source_record_id", nullable=False)
    op.create_unique_constraint(
        "uq_organization_dedup",
        "organization",
        ["source_name", "source_record_id"],
    )

    # politician_ideology_score: same pattern. Existing rows are seeded
    # with the previous dedup key (politician_id + congress + chamber) so
    # historical uniqueness is preserved before the new constraint swaps in.
    op.add_column(
        "politician_ideology_score",
        sa.Column("source_record_id", sa.String(length=100), nullable=True),
    )
    op.execute(
        "UPDATE politician_ideology_score SET source_record_id = "
        "'legacy-ideology-' || politician_id || '-' || congress || '-' || chamber "
        "WHERE source_record_id IS NULL"
    )
    op.alter_column("politician_ideology_score", "source_record_id", nullable=False)
    op.drop_constraint("uq_ideology_score", "politician_ideology_score", type_="unique")
    op.create_unique_constraint(
        "uq_ideology_score_dedup",
        "politician_ideology_score",
        ["source_name", "source_record_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_ideology_score_dedup", "politician_ideology_score", type_="unique"
    )
    op.create_unique_constraint(
        "uq_ideology_score",
        "politician_ideology_score",
        ["politician_id", "congress", "chamber"],
    )
    op.drop_column("politician_ideology_score", "source_record_id")

    op.drop_constraint("uq_organization_dedup", "organization", type_="unique")
    op.drop_column("organization", "source_record_id")
    op.drop_column("organization", "source_name")

    op.drop_constraint("fk_contribution_politician_id", "contribution", type_="foreignkey")
    op.drop_column("contribution", "politician_id")
