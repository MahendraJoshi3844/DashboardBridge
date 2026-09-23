"""The project lifecycle, persisted.

Three tables and no more: a `Project`, the `Artifact`s that belong to it, and the
`Job`s that ran against it. Analysis, conversion and validation results are
Phase 2+ and are deliberately absent — a table added before its consumer exists
is a guess about a shape nobody has needed yet.

Two rules from `09-security-spec.md` are structural here, not procedural:

* **An artifact's bytes are never in the database.** A row records where the
  bytes are (`storage_key`) and what they were (`sha256`). There is no column
  that could hold content, so the rule cannot be broken by accident.
* **Row data is never stored, anywhere.** The system reads schema only; extracts
  are never opened, so nothing derived from a cell has a home here.

Enum columns are stored as their wire values (`tableau`, not `TABLEAU`), because
the wire value is the contract in `packages/contracts` and the Python member
name is an implementation detail.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from dashboardbridge_contracts.enums import JobStatus, Platform, Stage
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enum(python_enum: type[enum.Enum], name: str) -> Enum:
    """A portable enum column holding the wire value.

    `native_enum=False` keeps it a VARCHAR + CHECK on Postgres as well as
    SQLite, so adding a value is an ordinary migration rather than an
    `ALTER TYPE` that cannot run inside a transaction.
    """
    return Enum(
        python_enum,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda e: [member.value for member in e],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    pass


class ArtifactKind(str, enum.Enum):
    """Which side of the migration an artifact sits on."""

    SOURCE = "source"
    TARGET = "target"


class JobKind(str, enum.Enum):
    """The three long-running operations of the API (05-api-spec)."""

    ANALYSIS = "analysis"
    CONVERSION = "conversion"
    VALIDATION = "validation"


#: A job in one of these states is finished. Reopening one would make the audit
#: trail a lie, so `transition_to` refuses it.
TERMINAL_STATUSES = frozenset(
    {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
)


class Project(Base):
    """One migration: a named pairing of a source platform and a target."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "source_platform <> target_platform",
            name="ck_projects_platforms_differ",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200))
    source_platform: Mapped[Platform] = mapped_column(_enum(Platform, "platform"))
    target_platform: Mapped[Platform] = mapped_column(_enum(Platform, "platform"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Artifact.created_at",
    )
    jobs: Mapped[list[Job]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Job.created_at",
    )


class Artifact(Base):
    """A reference to stored bytes. Never the bytes.

    `filename` is the sanitised display name and is never used to build a path;
    `storage_key` is the generated location the storage abstraction owns.
    """

    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifacts_project_id", "project_id"),
        CheckConstraint("size_bytes >= 0", name="ck_artifacts_size_non_negative"),
        CheckConstraint("length(sha256) = 64", name="ck_artifacts_sha256_length"),
    )

    artifact_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.project_id", ondelete="CASCADE"),
    )
    kind: Mapped[ArtifactKind] = mapped_column(_enum(ArtifactKind, "artifact_kind"))
    #: Sanitised, for display only. Never joined onto a path (§15).
    filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    #: Content hash of what was stored. The integrity record, not the content.
    sha256: Mapped[str] = mapped_column(String(64))
    #: Opaque key into the storage abstraction — local FS, S3, Azure Blob.
    storage_key: Mapped[str] = mapped_column(String(512))
    #: From `adapter.detect()`. `None` means detection was inconclusive, which
    #: is refused upstream rather than guessed.
    detected_platform: Mapped[Platform | None] = mapped_column(
        _enum(Platform, "platform"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    project: Mapped[Project] = relationship(back_populates="artifacts")


class Job(Base):
    """A long-running operation and the record of what became of it.

    Status changes go through `transition_to` so `started_at` / `finished_at`
    are recorded by the same code that changes the status; a timestamp set by
    hand somewhere else is how audit trails drift out of true.
    """

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_project_id", "project_id"),)

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.project_id", ondelete="CASCADE"),
    )
    kind: Mapped[JobKind] = mapped_column(_enum(JobKind, "job_kind"))
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.QUEUED
    )
    #: The stage last reported by the job's real event sink. Never synthesised.
    stage: Mapped[Stage | None] = mapped_column(_enum(Stage, "stage"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: The job's output, as the contract the API returns. Held here rather than
    #: in the artifact store because it is a result, not an artifact - it is
    #: queried, not downloaded. Row data never appears in it: the canonical
    #: model holds schema only.
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    #: The engine's own recording of the run: one entry per item it handled,
    #: in the order it handled them. Held so the event stream can replay a
    #: finished conversion instead of re-enacting it - a replay built from
    #: anything but the recording is a re-enactment, and would drift.
    timeline: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    #: Failure carries a category and two messages, always both (§46).
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: For a person. Never a stack trace, a path or an HTTP code.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: For an engineer, behind *View technical details*.
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship(back_populates="jobs")

    # -- transitions --------------------------------------------------------

    def transition_to(
        self, status: JobStatus, *, stage: Stage | None = None
    ) -> None:
        """Move to `status`, stamping the clock the move implies.

        A terminal job never restarts: a conversion that reports completed and
        then runs again would make both the audit trail and the SSE timeline
        untrue. A retry is a new job.
        """
        if self.status in TERMINAL_STATUSES:
            raise ValueError(
                f"job {self.job_id} is {self.status.value} and cannot move to "
                f"{status.value}; a retry is a new job"
            )
        now = _utcnow()
        if status is JobStatus.RUNNING and self.started_at is None:
            self.started_at = now
        if status in TERMINAL_STATUSES:
            self.finished_at = now
        if stage is not None:
            self.stage = stage
        self.status = status

    def fail(self, *, category: str, message: str, detail: str) -> None:
        """Record a failure with both messages. Neither substitutes for the other."""
        self.error_category = category
        self.error_message = message
        self.error_detail = detail
        self.transition_to(JobStatus.FAILED)


class Proposal(Base):
    """A model's drafted translation, and what a person decided about it.

    Stored rather than recomputed for two reasons. A decision is a *fact about a
    person*, not about a run, and re-asking a model would produce a different
    draft to decide about. And §62 wants AI accepted, rejected and still under
    review separable after the fact, which needs the rejected ones kept - a
    proposal a reviewer turned down is evidence about the model, and deleting it
    quietly improves the accuracy metrics.
    """

    __tablename__ = "proposals"
    __table_args__ = (Index("ix_proposals_project_id", "project_id"),)

    proposal_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.project_id", ondelete="CASCADE"),
    )
    #: `"<table>.<name>"`, the same address flags and events use.
    item: Mapped[str] = mapped_column(String(512))
    #: The whole `ProposalReview`, so the reviewer sees exactly what was shown
    #: before - including the prompt that was sent.
    review: Mapped[dict] = mapped_column(JSON, default=dict)
    decision: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class User(Base):
    """A person who uses this deployment (`P7.1`).

    The product runs on the customer's premises and its users are their own
    people - developers and analysts converting workbooks, some of whom know
    Tableau, some Power BI, most neither in depth. Accounts are local to the
    deployment because that is what "runs in your environment" means: there is
    no vendor-side directory to authenticate against, and an air-gapped
    customer must still be able to add a colleague.

    **The password is never here.** `password_hash` holds a self-describing
    scrypt string from `engines/identity`; there is no column that could hold a
    password, so the rule cannot be broken by accident - the same shape as
    `Artifact` never holding bytes.

    `is_active` rather than deleting a row: a project records who converted it,
    and deleting the user would either orphan that or cascade away the history
    of who did what. A leaver is deactivated, their sessions stop working, and
    their seat is freed.
    """

    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    #: Case-insensitively unique; stored as given so it is displayed as chosen.
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(Text)
    #: The only privilege that exists: may add and deactivate other users. A
    #: role vocabulary with nothing to say would be a guess about a permission
    #: model nobody has asked for - everyone here converts.
    is_admin: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("uq_users_email_lower", func.lower(email), unique=True),
    )


class Session(Base):
    """One signed-in browser.

    **Only a digest of the token is stored.** A session token needs no cracking
    to be used, so a database read must not be a set of live sessions - the
    reason is in `engines/identity.session_digest`.

    Both expiries are recorded because they answer different questions.
    `expires_at` is absolute: a session ends eventually whatever the user does,
    so a browser left open on a shared machine does not stay signed in for
    ever. `last_seen_at` drives the idle cutoff, which is what closes the
    laptop nobody came back to.
    """

    __tablename__ = "sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    #: SHA-256 of the token handed to the browser. Never the token.
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: Set when signed out or revoked. Kept rather than deleted so "this
    #: session ended" and "this session never existed" stay distinguishable.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    user: Mapped[User] = relationship(back_populates="sessions")
