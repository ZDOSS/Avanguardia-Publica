"""phase 3 financial disclosure politician_id nullable

The FinancialDisclosure model was created with ``politician_id NOT NULL``,
but Phase 3 introduces data sources that legitimately have no politician
linkage:

- SEC EDGAR Form 4 corporate insider filings (officers, directors, >10%
  holders — not politicians)
- Quiver Quant rows that don't fuzzy-match a legislator in our DB

Without this change, every insert from those adapters raises an
``IntegrityError`` and the base-class savepoint handler silently drops
the row, so 100% of Form 4 and unmatched Quiver records are lost.

Revision ID: 5b8e498be220
Revises: c3e61c962fc7
Create Date: 2026-06-09 00:00:00.000000
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "5b8e498be220"
down_revision: str | None = "c3e61c962fc7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "financial_disclosure",
        "politician_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "financial_disclosure",
        "politician_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
