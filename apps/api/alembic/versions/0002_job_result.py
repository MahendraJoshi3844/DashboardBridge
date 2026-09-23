"""Add jobs.result — the job's output as the contract the API returns.

Held on the job rather than in the artifact store because it is a result, not an
artifact: it is queried, not downloaded. Row data never appears in it, since the
canonical model holds schema only.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("result", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "result")
