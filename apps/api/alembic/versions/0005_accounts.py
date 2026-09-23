"""Accounts and sessions (`P7.1`).

The product runs on the customer's premises, so its users are local to the
deployment: there is no vendor-side directory to authenticate against, and an
air-gapped customer must still be able to add a colleague.

Two shapes here are decisions rather than mechanics.

**`password_hash`, never a password.** There is no column that could hold one,
so the rule cannot be broken by accident - the same shape as `artifacts` having
nowhere to put bytes. `tests/dashboardbridge/test_db.py` enforces the naming:
a column about a credential must be named for the one-way form it holds.

**`token_digest`, never a token.** A session token needs no cracking to be
used, so a database read must not hand someone a set of live sessions. Unique
and indexed because every authenticated request looks a session up by it, which
is the hottest query in the application.

Users are deactivated, never deleted. A project records who converted it, and
removing the row would either orphan that or cascade away the history of who
did what.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Unique on the lowered address, not on the address. People type their own
    # capitalisation, and two accounts differing only in case is one person
    # locked out of the one they made on Tuesday.
    op.create_index(
        "uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True
    )

    op.create_table(
        "sessions",
        sa.Column("session_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_digest", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_token_digest", "sessions", ["token_digest"])


def downgrade() -> None:
    op.drop_index("ix_sessions_token_digest", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
