"""Initial schema: the project lifecycle.

Three tables — `projects`, `artifacts`, `jobs`. Deliberately no table holds
artifact bytes or row data: an artifact row records a `storage_key` and a
`sha256` and nothing else about its contents (09-security-spec.md).

Enums are `native_enum=False`, so on Postgres they are VARCHAR + CHECK rather
than a real `TYPE`. Adding a value then becomes an ordinary migration instead of
an `ALTER TYPE ... ADD VALUE`, which cannot run inside a transaction.

Revision ID: 0001
Revises:
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLATFORM = sa.Enum("tableau", "powerbi", name="platform", native_enum=False, length=32)


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_platform", PLATFORM, nullable=False),
        sa.Column("target_platform", PLATFORM, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # Converting a platform to itself is nonsense the API already rejects.
        # The constraint means no code path can write it directly either.
        sa.CheckConstraint(
            "source_platform <> target_platform", name="ck_projects_platforms_differ"
        ),
        sa.PrimaryKeyConstraint("project_id"),
    )

    op.create_table(
        "artifacts",
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("source", "target", name="artifact_kind", native_enum=False, length=32),
            nullable=False,
        ),
        # Sanitised display name. Never used to build a path (§15).
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        # Opaque key into the storage abstraction. The bytes live there.
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("detected_platform", PLATFORM, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(sha256) = 64", name="ck_artifacts_sha256_length"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_artifacts_size_non_negative"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.project_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("artifact_id"),
    )
    op.create_index("ix_artifacts_project_id", "artifacts", ["project_id"])

    op.create_table(
        "jobs",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "analysis",
                "conversion",
                "validation",
                name="job_kind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="job_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "stage",
            sa.Enum(
                "extract",
                "parse",
                "map",
                "translate",
                "generate",
                "validate",
                "report",
                name="stage",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # A failure carries a category and two messages, always both (§46).
        sa.Column("error_category", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.project_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_project_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_artifacts_project_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_table("projects")
