"""Persistence for the project lifecycle.

Three claims are load-bearing here and each one has a test rather than a comment:

1. The schema creates and migrates on SQLite with **no Postgres running**, so
   `pytest` and the desktop shell never need a database server (ADR-006).
2. **Artifacts are never stored in the database.** A row holds a storage key and
   a sha256; the bytes live behind the storage abstraction (09-security-spec).
3. **Row data is never stored, anywhere**, and no secret is a plain column.

Claims 2 and 3 are asserted against the metadata itself, not against a
particular model, so adding a `LargeBinary` column anywhere fails the build.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from dashboardbridge_contracts.enums import JobStatus, Platform, Stage
from sqlalchemy import LargeBinary, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import create_app_engine, database_url, redacted_database_url
from app.db.models import Artifact, ArtifactKind, Base, Job, JobKind, Project

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{(tmp_path / 'dashboardbridge.db').as_posix()}"


@pytest.fixture
def engine(sqlite_url: str):
    eng = create_app_engine(sqlite_url)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine) -> Session:
    with Session(engine) as s:
        yield s


@pytest.fixture
def project(session: Session) -> Project:
    p = Project(
        name="Sales migration",
        source_platform=Platform.TABLEAU,
        target_platform=Platform.POWERBI,
    )
    session.add(p)
    session.commit()
    return p


# ---------------------------------------------------------------------------
# the schema exists without a server
# ---------------------------------------------------------------------------


def test_the_schema_creates_on_sqlite_with_no_postgres_running(engine):
    """Postgres is the deployed target; it is not a prerequisite for a test."""
    tables = set(inspect(engine).get_table_names())
    assert {"projects", "artifacts", "jobs"} <= tables


def test_the_database_url_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/bridge")
    assert database_url() == "postgresql+psycopg://u:p@db:5432/bridge"


def test_the_default_needs_no_database_server(monkeypatch):
    """Nothing configured must still run, or local mode is a second build."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url().startswith("sqlite")


def test_a_connection_password_is_never_rendered():
    """Connection strings are never logged (09-security-spec § Logging)."""
    rendered = redacted_database_url("postgresql+psycopg://bridge:hunter2@db/bridge")
    assert "hunter2" not in rendered
    assert "bridge" in rendered


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------


def test_a_project_is_created_and_read_back_with_both_platforms(
    session: Session, project: Project
):
    project_id = project.project_id
    session.expunge_all()
    found = session.get(Project, project_id)

    assert found is not None
    assert found.name == "Sales migration"
    assert found.source_platform is Platform.TABLEAU
    assert found.target_platform is Platform.POWERBI
    assert found.created_at is not None


def test_platforms_are_stored_as_their_wire_values(session: Session, project: Project):
    """The database must hold `tableau`, not `TABLEAU`. The wire value is the
    contract; the Python member name is an implementation detail."""
    rows = session.execute(
        text("SELECT source_platform, target_platform FROM projects")
    ).all()
    assert [tuple(r) for r in rows] == [("tableau", "powerbi")]


def test_a_project_cannot_convert_a_platform_to_itself(session: Session):
    """The API rejects this too; the constraint means no code path can slip it
    past by writing the row directly."""
    session.add(
        Project(
            name="nonsense",
            source_platform=Platform.TABLEAU,
            target_platform=Platform.TABLEAU,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ---------------------------------------------------------------------------
# artifacts — a reference, never the bytes
# ---------------------------------------------------------------------------


def test_an_artifact_stores_a_storage_reference_and_a_sha256(
    session: Session, project: Project
):
    artifact = Artifact(
        project_id=project.project_id,
        kind=ArtifactKind.SOURCE,
        filename="Superstore.twbx",
        size_bytes=4_194_304,
        sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        storage_key="projects/2f9c/01J8-source.twbx",
        detected_platform=Platform.TABLEAU,
    )
    session.add(artifact)
    session.commit()
    artifact_id = artifact.artifact_id
    session.expunge_all()

    found = session.get(Artifact, artifact_id)
    assert found is not None
    assert found.storage_key == "projects/2f9c/01J8-source.twbx"
    assert len(found.sha256) == 64
    assert found.size_bytes == 4_194_304
    assert found.detected_platform is Platform.TABLEAU


def test_an_artifact_row_has_nowhere_to_put_file_bytes():
    """Not "we do not write bytes" — there is no column that could hold them."""
    columns = Base.metadata.tables["artifacts"].columns
    assert not any(isinstance(c.type, LargeBinary) for c in columns)
    assert "content" not in columns
    assert "data" not in columns
    assert "bytes" not in columns
    assert "blob" not in columns


def test_no_table_anywhere_can_hold_bytes_or_row_data():
    """Row data is never stored, anywhere (02-architecture § Storage). A binary
    column is how that rule gets broken quietly, so the metadata is asserted."""
    forbidden = {"rows", "row_data", "sample_rows", "preview", "extract", "values"}
    for name, table in Base.metadata.tables.items():
        for column in table.columns:
            assert not isinstance(column.type, LargeBinary), (
                f"{name}.{column.name} is binary; artifacts and row data live in "
                "storage, never in the database"
            )
            assert column.name not in forbidden, f"{name}.{column.name} smells like row data"


#: Suffixes that say a column holds something one-way rather than something
#: recoverable. `P7.1` needed two such columns and there was nowhere else they
#: could live: a password hash and a session token digest have to be in the
#: database or there is no way to check either.
_ONE_WAY = ("_hash", "_digest")


def test_no_secret_is_a_plain_column():
    """Keys go through the secret provider, never a column (09-security-spec).

    The rule is about *recoverable* secrets. A password hash and a session token
    digest are not that, and both must be stored - so instead of exempting the
    accounts tables, the check now demands that any column whose name is about a
    credential is named for the one-way form it holds.

    That is a stronger guard than the blanket ban it replaces. `password` would
    fail; `password_hash` passes and says what it is. A future column called
    `api_key` still fails, and `api_key_hash` would pass and be correct.
    """
    forbidden = ("api_key", "secret", "token", "password", "credential", "connection_string")
    for name, table in Base.metadata.tables.items():
        for column in table.columns:
            lowered = column.name.lower()
            for word in forbidden:
                if word not in lowered:
                    continue
                assert lowered.endswith(_ONE_WAY), (
                    f"{name}.{column.name} names a credential. If it must be "
                    f"stored at all, store the one-way form and end the name "
                    f"in one of {_ONE_WAY} so the column says so."
                )


def test_an_artifact_must_belong_to_a_real_project(session: Session):
    """Every read is authorised against a project; an orphan row would be an
    object id with no owner to authorise against (09-security-spec § Tenancy)."""
    session.add(
        Artifact(
            project_id=uuid.uuid4(),
            kind=ArtifactKind.SOURCE,
            filename="orphan.twbx",
            size_bytes=1,
            sha256="0" * 64,
            storage_key="nowhere",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


def test_a_job_records_its_status_transitions(session: Session, project: Project):
    job = Job(project_id=project.project_id, kind=JobKind.ANALYSIS)
    session.add(job)
    session.commit()

    assert job.status is JobStatus.QUEUED
    assert job.started_at is None and job.finished_at is None

    job.transition_to(JobStatus.RUNNING, stage=Stage.PARSE)
    session.commit()
    assert job.status is JobStatus.RUNNING
    assert job.stage is Stage.PARSE
    assert job.started_at is not None
    assert job.finished_at is None

    job.transition_to(JobStatus.COMPLETED)
    session.commit()
    job_id = job.job_id
    session.expunge_all()

    found = session.get(Job, job_id)
    assert found is not None
    assert found.status is JobStatus.COMPLETED
    assert found.started_at is not None
    assert found.finished_at is not None
    assert found.finished_at >= found.started_at


def test_a_finished_job_cannot_quietly_start_again(session: Session, project: Project):
    """A terminal job that reopens would make the audit trail a lie."""
    job = Job(project_id=project.project_id, kind=JobKind.CONVERSION)
    session.add(job)
    session.commit()

    job.transition_to(JobStatus.RUNNING)
    job.transition_to(JobStatus.FAILED)
    with pytest.raises(ValueError):
        job.transition_to(JobStatus.RUNNING)


def test_a_failed_job_carries_both_messages(session: Session, project: Project):
    """One for a person, one for an engineer — always both (§46)."""
    job = Job(project_id=project.project_id, kind=JobKind.CONVERSION)
    session.add(job)
    session.commit()

    job.transition_to(JobStatus.RUNNING)
    job.fail(
        category="PARSER_ERROR",
        message="We could not read the workbook.",
        detail="lxml.etree.XMLSyntaxError: mismatched tag, line 4412",
    )
    session.commit()
    job_id = job.job_id
    session.expunge_all()

    found = session.get(Job, job_id)
    assert found is not None
    assert found.status is JobStatus.FAILED
    assert found.error_category == "PARSER_ERROR"
    assert found.error_message and found.error_detail
    assert "XMLSyntaxError" not in found.error_message


def test_deleting_a_project_takes_its_jobs_and_artifacts_with_it(
    session: Session, project: Project
):
    session.add(
        Artifact(
            project_id=project.project_id,
            kind=ArtifactKind.SOURCE,
            filename="a.twbx",
            size_bytes=1,
            sha256="1" * 64,
            storage_key="k",
        )
    )
    session.add(Job(project_id=project.project_id, kind=JobKind.ANALYSIS))
    session.commit()

    session.delete(project)
    session.commit()

    assert session.query(Artifact).count() == 0
    assert session.query(Job).count() == 0


# ---------------------------------------------------------------------------
# the migration is the schema
# ---------------------------------------------------------------------------


def test_the_alembic_migration_builds_the_same_schema_on_sqlite(
    tmp_path: Path, monkeypatch
):
    """A migration that has drifted from the models is worse than none: it
    passes locally and fails on the deployed database."""
    from alembic import command
    from alembic.config import Config

    url = f"sqlite+pysqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    cfg = Config(str(REPO_ROOT / "apps" / "api" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "apps" / "api" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        migrated = {
            name: {c["name"] for c in inspector.get_columns(name)}
            for name in inspector.get_table_names()
            if name != "alembic_version"
        }
    finally:
        engine.dispose()

    expected = {
        name: {c.name for c in table.columns}
        for name, table in Base.metadata.tables.items()
    }
    assert migrated == expected
