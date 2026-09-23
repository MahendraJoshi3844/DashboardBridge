"""Add jobs.timeline — the engine's recording of what the run handled.

Kept beside `result` rather than inside it because it answers a different
question: `result` is what the conversion produced, `timeline` is what it did,
item by item, in order. The event stream replays this recording; a stream
assembled from anything else would be a re-enactment and would drift from the
run it claims to describe.

Row data never appears in it — an event carries an object's name, its outcome,
and for a calculation the expression on each side, all of which are schema.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("timeline", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "timeline")
