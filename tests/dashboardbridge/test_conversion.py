"""Conversion: a stored artifact becomes a Power BI project.

The rule these tests exist to protect: nothing is reported as converted that the
engine did not convert, and producing a file is not evidence that it is correct.
"""

import io
import zipfile
from pathlib import Path

import pytest
from dashboardbridge_contracts import ConversionFlag
from dashboardbridge_contracts.enums import ConversionStatus
from tests.support.engines import needs_tableau

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _ready(client) -> str:
    """A project with an uploaded, analysed workbook."""
    project_id = client.post(
        "/api/v1/projects",
        json={
            "source_platform": "tableau",
            "target_platform": "powerbi",
            "name": "Conversion test",
        },
    ).json()["project_id"]
    client.post(
        f"/api/v1/projects/{project_id}/artifacts",
        files={
            "file": (
                "sample.twb",
                (FIXTURES / "sample.twb").read_bytes(),
                "application/octet-stream",
            )
        },
    )
    client.post(f"/api/v1/projects/{project_id}/analysis")
    return project_id


@pytest.fixture
def converted(api):
    client = api.client
    project_id = _ready(client)
    started = client.post(
        f"/api/v1/projects/{project_id}/conversion",
        json={"ai_enabled": False, "provider": "none", "privacy_mode": "local_only"},
    )
    assert started.status_code == 202, started.text
    result = client.get(f"/api/v1/projects/{project_id}/conversion")
    assert result.status_code == 200, result.text
    return project_id, result.json()


# --- the request contract --------------------------------------------------


@needs_tableau
def test_conversion_returns_a_job_naming_its_kind(api):
    client = api.client
    project_id = _ready(client)
    body = client.post(
        f"/api/v1/projects/{project_id}/conversion", json={"ai_enabled": False}
    ).json()
    assert body["kind"] == "conversion"


@needs_tableau
def test_converting_before_analysis_is_refused_in_the_users_terms(api):
    client = api.client
    project_id = client.post(
        "/api/v1/projects",
        json={
            "source_platform": "tableau",
            "target_platform": "powerbi",
            "name": "No analysis",
        },
    ).json()["project_id"]
    response = client.post(
        f"/api/v1/projects/{project_id}/conversion", json={"ai_enabled": False}
    )
    assert response.status_code == 400
    assert "Traceback" not in response.json()["message"]


def test_a_contradictory_request_is_refused_not_guessed_at(api):
    """ai_enabled with no provider is contradictory; guessing an intent here
    would be exactly the wrong instinct for this product."""
    client = api.client
    project_id = _ready(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/conversion",
        json={"ai_enabled": True, "provider": "none"},
    )
    assert response.status_code in {400, 422}


def test_local_only_refuses_a_remote_provider(api):
    client = api.client
    project_id = _ready(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/conversion",
        json={
            "ai_enabled": True,
            "provider": "openai_compatible",
            "privacy_mode": "local_only",
        },
    )
    assert response.status_code in {400, 422}


# --- what conversion reports ----------------------------------------------


@needs_tableau
def test_the_parts_sum_to_the_whole(converted):
    """A reader must be able to check the arithmetic."""
    _, body = converted
    c = body["compatibility"]
    assert (
        c["converted"] + c["partial"] + c["ai_required"] + c["unsupported"] + c["failed"]
        == c["total"]
    )


@needs_tableau
def test_every_refusal_survives_into_the_reported_flags(converted):
    """The engine refuses RUNNING_SUM. That refusal must reach the API rather
    than being smoothed away into a count."""
    _, body = converted
    assert any("Running Total" in flag["item"] for flag in body["flags"])


@needs_tableau
def test_flags_carry_all_three_axes(converted):
    _, body = converted
    for flag in body["flags"]:
        assert flag["method"] and flag["status"] and flag["severity"]


@needs_tableau
def test_conversion_names_the_artifact_it_produced(converted):
    _, body = converted
    assert body["artifact_id"]


# --- the produced artifact -------------------------------------------------


@needs_tableau
def test_the_artifact_downloads_as_a_pbip_project(api, converted):
    project_id, _ = converted
    response = api.client.get(f"/api/v1/projects/{project_id}/artifact")
    assert response.status_code == 200

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = archive.namelist()
    assert any(n.endswith(".pbip") for n in names), names
    assert any("SemanticModel" in n and n.endswith("model.tmdl") for n in names), names
    assert any("Report" in n and n.endswith("definition.pbir") for n in names), names


@needs_tableau
def test_every_emitted_table_carries_a_partition(api, converted):
    """Power BI rejects a semantic model whose table has no partition, so this
    is a structural precondition for the output opening at all."""
    project_id, _ = converted
    archive = zipfile.ZipFile(
        io.BytesIO(api.client.get(f"/api/v1/projects/{project_id}/artifact").content)
    )
    tables = [
        n for n in archive.namelist() if "/tables/" in n and n.endswith(".tmdl")
    ]
    assert tables, "no table files were produced"
    for name in tables:
        assert "partition" in archive.read(name).decode("utf-8"), name


@needs_tableau
def test_downloading_before_conversion_is_refused_not_served_partially(api):
    """A partial artifact must never be served as if it were finished."""
    client = api.client
    project_id = _ready(client)
    assert client.get(f"/api/v1/projects/{project_id}/artifact").status_code == 409


# --- determinism -----------------------------------------------------------


@needs_tableau
def test_converting_the_same_workbook_twice_produces_identical_output(api):
    client = api.client
    digests = []
    for _ in range(2):
        project_id = _ready(client)
        client.post(
            f"/api/v1/projects/{project_id}/conversion", json={"ai_enabled": False}
        )
        archive = zipfile.ZipFile(
            io.BytesIO(
                client.get(f"/api/v1/projects/{project_id}/artifact").content
            )
        )
        # Compare contents, not the zip bytes: archive metadata carries a
        # timestamp, and that is not part of the conversion's output.
        digests.append(
            {name: archive.read(name) for name in sorted(archive.namelist())}
        )
    assert digests[0] == digests[1]


# --- the denominator ------------------------------------------------------


@needs_tableau
def test_the_denominator_counts_every_object_that_can_be_flagged():
    """A flag about an object outside the total makes the total a fiction.

    Worksheet filters and dashboards are reported one by one, so a workbook with
    many filters produces more flags than there are columns, worksheets and
    tables put together. When the denominator counts only the latter, every
    object that converted cleanly is subtracted away and the screen says
    "0 of 133 converted" for a run in which twenty-six things converted
    perfectly. Under-claiming is safer than over-claiming and is still false.
    """
    from dashboardbridge_contracts.enums import (  # noqa: PLC0415
        ConversionMethod,
        Severity,
        Stage,
    )
    from engines.conversion.run import _compatibility  # noqa: PLC0415

    stats = {
        "tables": 5,
        "columns": 54,
        "worksheets": 21,
        "parameters": 6,
        "relationships": 2,
        "dashboards": 6,
        "filters": 65,
    }
    flags = [
        ConversionFlag(
            item=f"Sheet {i}: filter",
            stage=Stage.MAP,
            method=ConversionMethod.MANUAL,
            status=ConversionStatus.UNSUPPORTED,
            severity=Severity.MANUAL,
            reason="not carried over",
            ref=f"Sheet {i}: filter",
        )
        for i in range(110)
    ]

    result = _compatibility(stats, flags)
    assert result.total == sum(stats.values()), "the total is the objects considered"
    assert result.converted > 0, "objects with no flag against them converted"
    assert (
        result.converted
        + result.partial
        + result.ai_required
        + result.unsupported
        + result.failed
        == result.total
    )


# --- what "needs AI" is allowed to mean -----------------------------------


@needs_tableau
def test_only_calculations_are_reported_as_ai_addressable(converted):
    """AI_REQUIRED must mean "a model could draft this", not "a human must act".

    A worksheet filter, a dashboard layout or an unbindable field well needs a
    person to rebuild it; no model can. Counting those as AI_REQUIRED tells the
    user a model would clear 51 items when it could attempt six, which is a
    false promise dressed as a number.
    """
    _, body = converted
    for flag in body["flags"]:
        if flag["status"] == "ai_required":
            assert flag["stage"] == "translate", (
                f"{flag['item']} is stage={flag['stage']} and cannot be drafted "
                "by a model"
            )


@needs_tableau
def test_structural_refusals_are_reported_as_unsupported(converted):
    _, body = converted
    structural = [
        f for f in body["flags"] if f["stage"] in {"map", "generate"} and f["severity"] == "manual"
    ]
    assert structural, "the sample workbook should produce structural refusals"
    for flag in structural:
        assert flag["status"] == "unsupported"


# --- the comparison explorer needs both sides -----------------------------


@needs_tableau
def test_conversion_returns_the_translated_model(converted):
    """The flagship screen is source expression beside target expression.

    Without the produced DAX crossing the API, that screen has an empty column
    for every row - a comparison with nothing to compare.
    """
    _, body = converted
    assert body.get("model"), "conversion must carry the model it produced"


@needs_tableau
def test_a_converted_calculation_carries_its_dax(converted):
    _, body = converted
    columns = [
        column
        for datasource in body["model"]["datasources"]
        for table in datasource["tables"]
        for column in table["columns"]
        if column["expression"]
    ]
    translated = [c for c in columns if c["translation"]]
    assert translated, "no calculation carried a translation"
    for column in translated:
        assert column["translation"]["target_language"] == "dax"
        assert column["translation"]["target_text"]
        assert column["translation"]["method"] == "deterministic"


@needs_tableau
def test_a_refused_calculation_carries_no_translation(converted):
    """An empty target column is the honest rendering of a refusal. Inventing
    one would be the guess this product exists to refuse."""
    _, body = converted
    refused = [
        column
        for datasource in body["model"]["datasources"]
        for table in datasource["tables"]
        for column in table["columns"]
        if column["expression"] and not column["translation"]
    ]
    assert refused, "the sample workbook refuses RUNNING_SUM"
    for column in refused:
        assert any(column["name"] in flag["item"] for flag in body["flags"])
