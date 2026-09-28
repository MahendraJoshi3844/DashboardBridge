"""Extracted files: a Tableau conversion offers its metadata, what each item
became, and a validation report, as downloads (SPEC-extracted-files)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from tests.support.engines import needs_tableau

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PREFIX = "/api/v1"


def _project(client, source: str = "tableau") -> str:
    response = client.post(f"{PREFIX}/projects",
                           json={"source_platform": source, "target_platform": "powerbi", "name": "Extraction"})
    assert response.status_code in {200, 201}, response.text
    return response.json()["project_id"]


def _converted(client) -> str:
    project_id = _project(client)
    upload = client.post(f"{PREFIX}/projects/{project_id}/artifacts",
                         files={"file": ("sample.twb", (FIXTURES / "sample.twb").read_bytes(),
                                         "application/octet-stream")})
    assert upload.status_code == 201, upload.text
    client.post(f"{PREFIX}/projects/{project_id}/analysis")
    started = client.post(f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False})
    assert started.status_code == 202, started.text
    return project_id


@needs_tableau
def test_the_files_tab_lists_extraction_report_and_project(api):
    client = api.client
    project_id = _converted(client)
    body = client.get(f"{PREFIX}/projects/{project_id}/files").json()
    assert body["extraction_available"] is True and body["note"] is None
    assert body["validation"] == "PASSED"
    assert [f["kind"] for f in body["files"]] == ["extraction", "validation_report", "target"]
    for entry in body["files"]:
        download = client.get(f"{PREFIX}{entry['href']}")
        assert download.status_code == 200, entry
        assert entry["filename"] in download.headers["content-disposition"]


@needs_tableau
def test_the_archive_holds_metadata_report_source_and_project(api):
    client = api.client
    project_id = _converted(client)
    download = client.get(f"{PREFIX}/projects/{project_id}/extraction")
    assert download.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(download.content))
    names = set(archive.namelist())
    for required in ("extracted/manifest.json", "extracted/calculations.json", "extracted/worksheets.json",
                     "extracted/page_mapping.json", "VALIDATION_REPORT.md", "validation.json",
                     "source/sample.twb"):
        assert required in names, required
    assert any(n.startswith("powerbi/") and n.endswith(".pbip") for n in names)
    manifest = json.loads(archive.read("extracted/manifest.json"))
    # reported under the uploaded file's name, not the engine's staging copy
    assert manifest["source"]["file"] == "sample.twb"
    assert manifest["source"]["data_included"] is False


@needs_tableau
def test_the_validation_report_downloads_on_its_own(api):
    client = api.client
    project_id = _converted(client)
    report = client.get(f"{PREFIX}/projects/{project_id}/validation-report")
    assert report.status_code == 200
    assert report.text.startswith("# Validation report")


@needs_tableau
def test_recompile_replaces_the_files_without_a_new_upload(api):
    client = api.client
    project_id = _converted(client)
    first = client.get(f"{PREFIX}/projects/{project_id}/extraction").content
    again = client.post(f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False})
    assert again.status_code == 202
    second = client.get(f"{PREFIX}/projects/{project_id}/extraction").content
    listed = {n: zipfile.ZipFile(io.BytesIO(b)).read("extracted/calculations.json") for n, b in
              (("first", first), ("second", second))}
    assert listed["first"] == listed["second"]  # deterministic across runs


def test_before_conversion_the_files_tab_says_so(api):
    client = api.client
    project_id = _project(client)
    body = client.get(f"{PREFIX}/projects/{project_id}/files").json()
    assert body["files"] == [] and body["extraction_available"] is False
    assert "converted" in body["note"]
    missing = client.get(f"{PREFIX}/projects/{project_id}/extraction")
    assert missing.status_code == 404
    assert "Convert the workbook first" in missing.json()["message"]


@pytest.mark.parametrize("source", ["microstrategy", "qlik"])
def test_other_directions_say_plainly_that_there_are_no_extracted_files(api, source):
    client = api.client
    project_id = _project(client, source)
    missing = client.get(f"{PREFIX}/projects/{project_id}/extraction")
    assert missing.status_code == 404
    assert "Tableau to Power BI migrations" in missing.json()["message"]
