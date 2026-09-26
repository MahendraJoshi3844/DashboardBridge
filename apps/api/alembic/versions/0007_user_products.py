"""Per-user product access: which migration products each person may use.

Tableau, MicroStrategy and Qlik migration are separate products. An
administrator decides who may use which; administrators themselves always have
every product the licence includes.

Every account that exists before this revision is granted all three products:
until now everyone could use every direction, and an upgrade must not quietly
take that away. What the licence does not cover stays unavailable regardless.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels = None
depends_on = None

PRODUCTS = ("tableau", "microstrategy", "qlik")


def upgrade() -> None:
    op.create_table(
        "user_products",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("product", sa.String(32), primary_key=True),
    )
    users = sa.table("users", sa.column("user_id", sa.Uuid()))
    grants = sa.table("user_products", sa.column("user_id", sa.Uuid()), sa.column("product", sa.String(32)))
    connection = op.get_bind()
    rows = [{"user_id": uid, "product": p} for (uid,) in connection.execute(sa.select(users.c.user_id)) for p in PRODUCTS]
    if rows:
        op.bulk_insert(grants, rows)


def downgrade() -> None:
    op.drop_table("user_products")
