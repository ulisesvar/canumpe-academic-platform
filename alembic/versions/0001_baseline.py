"""baseline (empty schema)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-15

Phase 0 baseline. No academic domain tables exist yet; this migration
establishes the alembic_version bookkeeping table against an otherwise
empty database. Domain tables are introduced in a later phase.
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
