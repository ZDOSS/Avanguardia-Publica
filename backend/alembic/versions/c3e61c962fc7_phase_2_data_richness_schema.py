"""phase 2 data richness schema additions

Adds columns/constraints that were originally added in-place to the initial
schema migration. Alembic would treat those in-place edits as already
applied on any environment that ran Phase 1, so the new columns were never
created. This migration brings those environments up to the Phase 2 schema
without re-creating any of the 13 original tables.

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

    op.add_column(
        "organization",
        sa.Column("source_name", sa.String(length=50), nullable=False, server_default=""),
    )
    op.add_column(
        "organization",
        sa.Column("source_record_id", sa.String(length=100), nullable=False, server_default=""),
    )
    op.create_unique_constraint(
        "uq_organization_dedup",
        "organization",
        ["source_name", "source_record_id"],
    )
    op.alter_column("organization", "source_name", server_default=None)
    op.alter_column("organization", "source_record_id", server_default=None)

    op.add_column(
        "politician_ideology_score",
        sa.Column("source_record_id", sa.String(length=100), nullable=False, server_default=""),
    )
    op.drop_constraint("uq_ideology_score", "politician_ideology_score", type_="unique")
    op.create_unique_constraint(
        "uq_ideology_score_dedup",
        "politician_ideology_score",
        ["source_name", "source_record_id"],
    )
    op.alter_column("politician_ideology_score", "source_record_id", server_default=None)


def downgrade() -> None:
    op.alter_column(
        "politician_ideology_score",
        "source_record_id",
        existing_type=sa.String(length=100),
        nullable=False,
    )
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
