"""Artifacts carry a note, so a saved workspace version says what changed.

A produced project is versioned by its target artifacts: v0 is what the
converter wrote, and each save from the workspace adds one. The note is the
person's own line about the save. Nullable, because every artifact before this
revision has none and inventing one would put words in nobody's mouth.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("artifacts", sa.Column("note", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("artifacts", "note")
