"""Proposals, and what a person decided about each one.

A decision is a fact about a person rather than about a run, so it is stored
instead of recomputed: re-asking a model would produce a different draft to
decide about, and the decision would have nothing to attach to.

Rejected proposals are kept. §62 wants AI accepted, rejected and still under
review separable after the fact, and a rejected proposal is evidence about the
model - deleting it quietly improves the accuracy metrics.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proposals",
        sa.Column("proposal_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("projects.project_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item", sa.String(512), nullable=False),
        sa.Column("review", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_proposals_project_id", "proposals", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_proposals_project_id", table_name="proposals")
    op.drop_table("proposals")
