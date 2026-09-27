"""Uploading and analysing a Power BI project (`P6a.4`).

Phase 6a's acceptance criterion: *"upload a PBIP project, see its inventory."*
This is that, over the real API — upload, detect, analyse, count.

A PBIP is a *folder*, so it arrives zipped. That makes the extension a weak
signal: `.zip` says almost nothing, and `.twbx` is a zip too. So the platform is
settled by looking inside — a project contains a `.pbip`, `.pbism` or `.pbir`
member — exactly as `.twbx` is confirmed by containing a `.twb`. An extension is
a claim by whoever uploaded the file; the bytes are not.

None of the analysis needed changing. `inventory_of` takes a canonical model and
counts it, which is what "everything crosses the canonical model" is *for*: a
second source platform reaches the same dashboard without the dashboard knowing.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from tests.support.engines import needs_tableau

pytestmark = needs_tableau

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pbip"
PREFIX = "/api/v1"


def _zipped(directory: Path) -> bytes:
    """The fixture as a user would send it: the project folder, zipped."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, str(path.relative_to(directory)).replace("\\", "/"))
    return buffer.getvalue()


def _project(client, platform: str = "powerbi") -> str:
    """A project reading `platform`. The target is whatever it is not."""
    target = "tableau" if platform == "powerbi" else "powerbi"
    response = client.post(
        f"{PREFIX}/projects",
        json={
            "source_platform": platform,
            "target_platform": target,
            "name": "Retail",
        },
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()["project_id"]


def _uploaded(client) -> str:
    project_id = _project(client)
    response = client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={"file": ("Retail.zip", _zipped(FIXTURE), "application/zip")},
    )
    assert response.status_code in {200, 201}, response.text
    return project_id


# --- getting it in -----------------------------------------------------------


def test_a_zipped_project_is_accepted_and_recognised(api):
    project_id = _project(api.client)

    response = api.client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={"file": ("Retail.zip", _zipped(FIXTURE), "application/zip")},
    )

    assert response.status_code in {200, 201}, response.text
    assert response.json()["detected_platform"] == "powerbi"


def test_a_zip_that_is_not_a_project_is_refused_in_the_users_terms(api):
    """A `.zip` says almost nothing, so the bytes have to.

    Accepting any archive and failing later would turn "this is not a Power BI
    project" into a parser error a user cannot act on.
    """
    project_id = _project(api.client)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("holiday.jpg", b"not a project")

    response = api.client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={"file": ("holiday.zip", buffer.getvalue(), "application/zip")},
    )

    assert response.status_code == 400
    assert "Traceback" not in response.json()["message"]


def test_a_packaged_tableau_workbook_is_still_read_as_tableau(api):
    """Both are zips. The member list is what tells them apart."""
    project_id = _project(api.client, platform="tableau")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "book.twb",
            (Path(__file__).resolve().parents[1] / "fixtures" / "sample.twb").read_text(
                encoding="utf-8"
            ),
        )

    response = api.client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={"file": ("book.twbx", buffer.getvalue(), "application/zip")},
    )

    assert response.status_code in {200, 201}, response.text
    assert response.json()["detected_platform"] == "tableau"


# --- seeing its inventory ----------------------------------------------------


def test_the_inventory_counts_what_the_project_actually_holds(api):
    """The phase's acceptance criterion, over the API.

    Sales holds eight items and Store three; three of the eleven are
    calculated - one calculated column and two measures. One relationship, one
    page, one visual. Counted from the canonical model, never estimated.
    """
    project_id = _uploaded(api.client)

    started = api.client.post(f"{PREFIX}/projects/{project_id}/analysis")
    assert started.status_code == 202, started.text
    body = api.client.get(f"{PREFIX}/projects/{project_id}/analysis").json()

    inventory = body["inventory"]
    assert inventory["tables"] == 2
    assert inventory["columns"] == 11
    assert inventory["calculations"] == 3
    assert inventory["relationships"] == 1
    assert inventory["visuals"] == 1
    assert inventory["dashboards"] == 1


def test_the_analysis_returns_the_model_it_counted(api):
    project_id = _uploaded(api.client)
    api.client.post(f"{PREFIX}/projects/{project_id}/analysis")

    body = api.client.get(f"{PREFIX}/projects/{project_id}/analysis").json()

    assert body["model"]["source_platform"] == "powerbi"
    names = {
        table["name"]
        for datasource in body["model"]["datasources"]
        for table in datasource["tables"]
    }
    assert names == {"Sales", "Store"}


def test_the_complexity_score_travels_with_its_formula(api):
    """Same rule for a Power BI source as for a Tableau one: a score whose
    derivation a reader cannot follow is decoration."""
    project_id = _uploaded(api.client)
    api.client.post(f"{PREFIX}/projects/{project_id}/analysis")

    complexity = api.client.get(f"{PREFIX}/projects/{project_id}/analysis").json()[
        "complexity"
    ]

    assert 0.0 <= complexity["score"] <= 1.0
    assert "weights" in complexity["formula"]


def test_analysing_it_twice_gives_the_same_answer(api):
    project_id = _uploaded(api.client)
    api.client.post(f"{PREFIX}/projects/{project_id}/analysis")
    first = api.client.get(f"{PREFIX}/projects/{project_id}/analysis").json()
    api.client.post(f"{PREFIX}/projects/{project_id}/analysis")
    second = api.client.get(f"{PREFIX}/projects/{project_id}/analysis").json()

    for body in (first, second):
        body.pop("analysis_id")
    assert first == second


# --- what it must not claim --------------------------------------------------


def test_converting_a_power_bi_source_now_produces_a_tableau_workbook(api):
    """This asserted a refusal while `P6b` did not exist. It does now, and
    `SPEC-powerbi-to-tableau-web.md` wires it through; the direction is
    covered in depth by `test_powerbi_conversion_api.py`."""
    project_id = _uploaded(api.client)
    api.client.post(f"{PREFIX}/projects/{project_id}/analysis")

    response = api.client.post(
        f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False}
    )

    assert response.status_code == 202, response.text
    produced = api.client.get(f"{PREFIX}/projects/{project_id}/artifact")
    assert produced.headers["content-disposition"].endswith('.twb"')
