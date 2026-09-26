"""Artifact upload — the one place where attacker-controlled bytes enter.

`09-security-spec.md` treats an uploaded artifact as hostile. Every control it
lists at the upload boundary has a test here, and each test states the attack it
refuses rather than the code path it covers:

* the extension allow-list, with `.pbix` refused *clearly* (ADR-005) and a
  bare `.pbip` manifest answered with the remedy rather than a refusal
* a size limit enforced while streaming, not after the whole file is buffered
* the original filename never reaching a path — a display string and nothing more
* archive-bomb limits applied to every archive - `.twbx` and a zipped Power
  BI project alike - **before** anything is extracted; in fact nothing is ever
  extracted
* a `sha256` of exactly the bytes that were stored
* a detected platform that contradicts the project refused, never coerced

The zip bomb here is a real zip with a real declared uncompressed size. Mocking
the check would test that the mock returns what it was told to.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.db import create_app_engine, get_session
from app.core.errors import ApiException
from app.db.models import Artifact as ArtifactRow
from app.db.models import Base
from app.main import app
from app.services import upload_validation as uv
from app.services.artifact_store import (
    LocalFilesystemStore,
    StorageKeyError,
    get_artifact_store,
)

from tests.dashboardbridge.conftest import sign_in  # noqa: E402
from tests.support.engines import needs_tableau

PREFIX = "/api/v1"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE_TWB = FIXTURES / "sample.twb"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path: Path):
    engine = create_app_engine(f"sqlite+pysqlite:///{(tmp_path / 'api.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def _session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    store = LocalFilesystemStore(tmp_path / "artifacts")
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_artifact_store] = lambda: store

    with TestClient(app, raise_server_exceptions=False) as client:
        # Every data route requires a session (`P7.1`), including the one that
        # creates the project below. Shared with `conftest` rather than copied:
        # the copy is what drifted last time.
        sign_in(client, factory)
        project = client.post(
            f"{PREFIX}/projects",
            json={
                "source_platform": "tableau",
                "target_platform": "powerbi",
                "name": "Sales migration",
            },
        ).json()
        yield SimpleNamespace(
            client=client,
            store=store,
            root=tmp_path / "artifacts",
            project_id=project["project_id"],
            session=factory,
        )

    app.dependency_overrides.clear()
    engine.dispose()


def upload(api, name: str, data: bytes, project_id: str | None = None):
    return api.client.post(
        f"{PREFIX}/projects/{project_id or api.project_id}/artifacts",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
    )


def stored_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


def make_twbx(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def make_zip_bomb(uncompressed_mb: int = 24) -> bytes:
    """A real zip. Small on the wire, enormous when expanded."""
    return make_twbx({"Book.twb": b"\0" * (uncompressed_mb * 1024 * 1024)})


_LEAKS = (
    re.compile(r"[A-Za-z]:[\\/]"),
    re.compile(r"(?<!\w)/(?:home|usr|var|tmp|Users)/"),
    re.compile(r"Traceback"),
    re.compile(r"\b(?:400|401|403|404|409|413|422|500)\b(?!\s*(?:MB|GB|KB|bytes))"),
)


def assert_error_shape(body: dict) -> None:
    assert body["message"], "a message for a person is never optional"
    assert body["detail"], "a detail for an engineer is never optional"
    for leak in _LEAKS:
        assert not leak.search(body["message"]), (
            f"human message leaked {leak.pattern!r}: {body['message']!r}"
        )


# ---------------------------------------------------------------------------
# the happy path, and what it is allowed to claim
# ---------------------------------------------------------------------------


@needs_tableau
def test_a_twb_uploads_and_reports_its_own_bytes(api):
    payload = SAMPLE_TWB.read_bytes()
    response = upload(api, "sample.twb", payload)
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["kind"] == "source"
    assert body["filename"] == "sample.twb"
    assert body["size_bytes"] == len(payload)
    assert body["sha256"] == hashlib.sha256(payload).hexdigest()
    assert body["detected_platform"] == "tableau"


@needs_tableau
def test_the_stored_bytes_are_the_uploaded_bytes(api):
    payload = SAMPLE_TWB.read_bytes()
    upload(api, "sample.twb", payload)
    with api.session() as session:
        row = session.query(ArtifactRow).one()
    assert api.store.read(row.storage_key) == payload


@needs_tableau
def test_the_name_on_disk_is_never_the_name_that_was_uploaded(api):
    upload(api, "sample.twb", SAMPLE_TWB.read_bytes())
    names = [p.name for p in stored_files(api.root)]
    assert names, "something should have been stored"
    assert "sample.twb" not in names, "an attacker-controlled name must not name a file"
    assert all(not n.startswith("sample") for n in names)


@needs_tableau
def test_a_traversing_filename_is_display_text_and_nothing_more(api, tmp_path):
    response = upload(api, "../../../../evil.twb", SAMPLE_TWB.read_bytes())
    assert response.status_code == 201, response.text
    assert response.json()["filename"] == "evil.twb"
    assert all(api.root in p.parents for p in stored_files(api.root))
    assert not (tmp_path / "evil.twb").exists()


@needs_tableau
def test_a_twbx_is_accepted_without_being_extracted(api):
    payload = make_twbx(
        {"Book.twb": SAMPLE_TWB.read_bytes(), "Data/thumb.png": b"\x89PNG\r\n\x1a\n"}
    )
    response = upload(api, "Book.twbx", payload)
    assert response.status_code == 201, response.text
    assert response.json()["detected_platform"] == "tableau"
    # One stored object: the archive. Never its members.
    assert len(stored_files(api.root)) == 1


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


@needs_tableau
def test_an_extension_outside_the_allow_list_is_refused(api):
    response = upload(api, "payload.exe", b"MZ\x90\x00")
    assert response.status_code == 400
    body = response.json()
    assert body["category"] == "UPLOAD_ERROR"
    assert_error_shape(body)
    assert stored_files(api.root) == []


@needs_tableau
def test_power_bi_input_is_refused_clearly_rather_than_vaguely(api):
    """`.pbix` is a compressed SSAS model, not text, and is out of scope
    (ADR-005). PBIP *is* readable since `P6a`; this is the format that is not."""
    response = upload(api, "report.pbix", b"PK\x03\x04")
    assert response.status_code == 400
    body = response.json()
    assert body["category"] == "UNSUPPORTED_ARTIFACT"
    assert "Power BI" in body["message"]
    assert_error_shape(body)


def test_a_file_over_the_limit_is_refused(api, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")
    settings.cache_clear()
    try:
        response = upload(api, "big.twb", b"<workbook>" + b"x" * (3 * 1024 * 1024))
        assert response.status_code == 400, response.text
        body = response.json()
        assert body["category"] == "UPLOAD_ERROR"
        assert_error_shape(body)
        assert stored_files(api.root) == [], "an oversize file must not land on disk"
    finally:
        settings.cache_clear()


def test_a_body_that_declares_no_length_is_still_bounded(api, monkeypatch):
    """The limit must survive a client that simply declines to declare a size.

    `Content-Length` is a courtesy. A chunked upload has none, so the only
    control left is the one applied to the bytes as they arrive — which is the
    control that actually matters, and the one this test exercises. Everything
    here is real: httpx streams the generator, so the server sees a chunked
    body it must refuse mid-flight.
    """
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")
    settings.cache_clear()
    boundary = "----dashboardbridgetest"

    def body():
        yield (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="big.twb"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        yield b"<workbook>"
        for _ in range(48):
            yield b"x" * 65536  # 3 MB against a 1 MB limit
        yield f"\r\n--{boundary}--\r\n".encode()

    try:
        response = api.client.post(
            f"{PREFIX}/projects/{api.project_id}/artifacts",
            content=body(),
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
        assert "content-length" not in {
            k.lower() for k in response.request.headers
        }, "the point of this test is a body with no declared size"
        assert response.status_code == 400, response.text
        body_json = response.json()
        assert body_json["category"] == "UPLOAD_ERROR"
        assert "request body reached" in body_json["detail"], (
            "the refusal must come from the streamed cap, not from a declared "
            "size that was never sent"
        )
        assert_error_shape(body_json)
        assert stored_files(api.root) == []
    finally:
        settings.cache_clear()


@needs_tableau
def test_a_zip_bomb_is_refused_before_anything_is_extracted(api):
    response = upload(api, "bomb.twbx", make_zip_bomb())
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["category"] == "UPLOAD_ERROR"
    assert_error_shape(body)
    assert stored_files(api.root) == []


@needs_tableau
def test_a_twbx_that_is_not_a_zip_is_refused(api):
    response = upload(api, "Book.twbx", b"not a zip at all")
    assert response.status_code == 400
    assert_error_shape(response.json())


@needs_tableau
def test_content_that_is_not_a_workbook_is_refused_not_guessed(api):
    """Detection is inconclusive, so the answer is 'no', not a plausible guess."""
    response = upload(api, "sample.twb", b"just some text, no workbook here\n" * 10)
    assert response.status_code == 400
    assert_error_shape(response.json())


@needs_tableau
def test_a_detected_platform_that_contradicts_the_project_is_refused(api):
    other = api.client.post(
        f"{PREFIX}/projects",
        json={
            "source_platform": "powerbi",
            "target_platform": "tableau",
            "name": "The other direction",
        },
    ).json()

    response = upload(
        api,
        "Book.twbx",
        make_twbx({"Book.twb": SAMPLE_TWB.read_bytes()}),
        project_id=other["project_id"],
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["category"] == "UNSUPPORTED_ARTIFACT"
    assert_error_shape(body)
    assert stored_files(api.root) == []


def test_uploading_to_an_unknown_project_is_reported(api):
    response = upload(
        api,
        "sample.twb",
        SAMPLE_TWB.read_bytes(),
        project_id="11111111-1111-4111-8111-111111111111",
    )
    assert response.status_code == 404
    assert_error_shape(response.json())
    assert stored_files(api.root) == []


def test_no_artifact_row_survives_a_refused_upload(api):
    upload(api, "bomb.twbx", make_zip_bomb())
    with api.session() as session:
        assert session.query(ArtifactRow).count() == 0


# ---------------------------------------------------------------------------
# the storage abstraction on its own
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> LocalFilesystemStore:
    return LocalFilesystemStore(tmp_path / "artifacts")


def test_a_generated_key_carries_no_user_input(store):
    key = store.new_key(suffix=".twbx")
    assert key.endswith(".twbx")
    assert "sample" not in key
    assert store.new_key(suffix=".twbx") != key


@pytest.mark.parametrize(
    "key",
    [
        "../secrets.env",
        "a/../../secrets.env",
        "..\\secrets.env",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "",
        ".",
        "nested/../../out.twb",
    ],
)
def test_a_key_that_escapes_the_root_is_refused(store, key):
    with pytest.raises(StorageKeyError):
        store.read(key)


def test_a_key_that_escapes_the_root_is_refused_on_delete_too(store):
    with pytest.raises(StorageKeyError):
        store.delete("../secrets.env")


def test_a_traversing_key_never_reads_a_real_file_outside_the_root(store, tmp_path):
    secret = tmp_path / "secrets.env"
    secret.write_bytes(b"API_KEY=hunter2")
    with pytest.raises(StorageKeyError):
        store.read("../secrets.env")


def test_a_staged_write_that_is_not_committed_leaves_nothing_behind(store):
    with store.stage() as staged:
        staged.write(b"partial")
    assert stored_files(store.root) == []


def test_a_staged_write_is_committed_under_the_generated_key(store):
    key = store.new_key(suffix=".twb")
    with store.stage() as staged:
        staged.write(b"<workbook/>")
        staged.commit(key)
    assert store.read(key) == b"<workbook/>"


# ---------------------------------------------------------------------------
# the validation controls, each on its own
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\win.ini", "win.ini"),
        ("Book.twbx", "Book.twbx"),
        ("  spaced name .twb  ", "spaced name .twb"),
        ("nul\x00byte.twb", "nulbyte.twb"),
        ("..", "upload"),
        ("", "upload"),
        ("/", "upload"),
    ],
)
def test_filename_sanitisation(raw, expected):
    assert uv.sanitize_filename(raw) == expected


def test_a_sanitised_name_can_never_be_a_path_component_that_escapes():
    for raw in ("../../x.twb", "..\\x.twb", "/x.twb", "..", "."):
        cleaned = uv.sanitize_filename(raw)
        assert "/" not in cleaned and "\\" not in cleaned
        assert cleaned not in ("..", ".")


def test_the_extension_allow_list_names_what_is_allowed():
    assert uv.validated_extension("Book.TWBX") == ".twbx"
    assert uv.validated_extension("sample.twb") == ".twb"
    with pytest.raises(ApiException) as refused:
        uv.validated_extension("payload.exe")
    assert refused.value.category.value == "UPLOAD_ERROR"
    assert ".twb" in refused.value.message


def test_the_power_bi_formats_we_cannot_read_say_so():
    """`.pbix` is a compressed SSAS model, not text (ADR-005); `.pbit` likewise."""
    for name in ("report.pbix", "template.pbit"):
        with pytest.raises(ApiException) as refused:
            uv.validated_extension(name)
        assert refused.value.category.value == "UNSUPPORTED_ARTIFACT"
        assert "Power BI" in refused.value.message


def test_a_bare_pbip_manifest_is_refused_with_the_remedy_not_a_shrug():
    """PBIP became readable in `P6a`, so "not supported" would now be false.

    A `.pbip` is the project *manifest* - a few lines of JSON pointing at the
    folders beside it. Accepting it would produce an empty inventory rather than
    an error, and refusing it as unsupported would send a user away from a
    format that works. The message says what to upload instead.
    """
    with pytest.raises(ApiException) as refused:
        uv.validated_extension("project.pbip")

    assert refused.value.category.value == "UNSUPPORTED_ARTIFACT"
    assert "zip" in refused.value.message.lower()
    assert "manifest" in refused.value.message.lower()


def test_a_zipped_project_extension_is_allowed():
    assert uv.validated_extension("Retail.zip") == ".zip"


def test_the_size_limit_stops_the_stream_rather_than_measuring_the_result():
    written: list[int] = []

    def sink(chunk: bytes) -> None:
        written.append(len(chunk))

    chunks = (b"x" * 1024 for _ in range(1000))
    with pytest.raises(ApiException) as refused:
        uv.stream_with_limits(chunks, sink=sink, limit_bytes=4096)

    assert refused.value.category.value == "UPLOAD_ERROR"
    assert sum(written) <= 4096 + 1024, "the sink must not receive the whole file"


def test_the_declared_size_is_refused_before_a_byte_is_read():
    with pytest.raises(ApiException):
        uv.check_declared_size("99999999999", limit_bytes=1024)
    uv.check_declared_size(None, limit_bytes=1024)  # absent is not a failure


def test_streaming_computes_the_sha256_of_exactly_what_was_written():
    payload = SAMPLE_TWB.read_bytes()
    seen = bytearray()
    result = uv.stream_with_limits(
        iter([payload[:100], payload[100:]]),
        sink=seen.extend,
        limit_bytes=len(payload) + 1,
    )
    assert bytes(seen) == payload
    assert result.size_bytes == len(payload)
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.head.startswith(b"<?xml")


def test_zip_limits_refuse_a_bomb_by_its_compression_ratio(tmp_path):
    archive = tmp_path / "bomb.twbx"
    archive.write_bytes(make_zip_bomb())
    with pytest.raises(ApiException) as refused:
        uv.inspect_zip_archive(archive)
    assert refused.value.category.value == "UPLOAD_ERROR"
    assert "compress" in refused.value.detail.lower()


def test_zip_limits_refuse_too_many_entries(tmp_path):
    archive = tmp_path / "many.twbx"
    archive.write_bytes(make_twbx({f"f{n}.txt": b"a" for n in range(50)}))
    with pytest.raises(ApiException) as refused:
        uv.inspect_zip_archive(archive, limits=uv.ZipLimits(max_entries=10))
    assert "entries" in refused.value.detail.lower()


def test_zip_limits_refuse_a_total_expansion_over_the_cap(tmp_path):
    archive = tmp_path / "wide.twbx"
    archive.write_bytes(make_twbx({f"f{n}.txt": b"a" * 4096 for n in range(8)}))
    with pytest.raises(ApiException) as refused:
        uv.inspect_zip_archive(
            archive,
            limits=uv.ZipLimits(max_total_uncompressed_bytes=1024, max_ratio=100_000),
        )
    assert "total" in refused.value.detail.lower()


def test_zip_inspection_reads_the_directory_and_extracts_nothing(tmp_path):
    archive = tmp_path / "Book.twbx"
    archive.write_bytes(make_twbx({"Book.twb": SAMPLE_TWB.read_bytes()}))
    before = {p for p in tmp_path.rglob("*")}
    report = uv.inspect_zip_archive(archive)
    assert report.entry_count == 1
    assert report.names == ("Book.twb",)
    assert {p for p in tmp_path.rglob("*")} == before, "nothing was extracted"


def test_detection_is_cheap_and_refuses_to_guess(tmp_path):
    from dashboardbridge_contracts.enums import Platform

    twb = SAMPLE_TWB.read_bytes()
    assert uv.detect_platform(".twb", head=twb[:4096]) is Platform.TABLEAU
    assert uv.detect_platform(".twb", head=b"hello there") is None

    archive = tmp_path / "Book.twbx"
    archive.write_bytes(make_twbx({"Book.twb": twb}))
    report = uv.inspect_zip_archive(archive)
    assert uv.detect_platform(".twbx", head=b"PK\x03\x04", zip_report=report) is (
        Platform.TABLEAU
    )

    empty = tmp_path / "Empty.twbx"
    empty.write_bytes(make_twbx({"notes.txt": b"nothing"}))
    assert uv.detect_platform(
        ".twbx", head=b"PK\x03\x04", zip_report=uv.inspect_zip_archive(empty)
    ) is None
