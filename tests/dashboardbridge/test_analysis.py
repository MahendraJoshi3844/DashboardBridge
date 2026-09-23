"""Analysis: upload -> adapter -> canonical model -> inventory the UI can show.

The numbers produced here end up in front of someone scoping a migration
programme, so the tests pin what they mean rather than that they exist.
"""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _project(client) -> str:
    response = client.post(
        "/api/v1/projects",
        json={
            "source_platform": "tableau",
            "target_platform": "powerbi",
            "name": "Analysis test",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["project_id"]


def _upload(client, project_id: str, name: str = "sample.twb") -> None:
    data = (FIXTURES / name).read_bytes()
    response = client.post(
        f"/api/v1/projects/{project_id}/artifacts",
        files={"file": (name, data, "application/octet-stream")},
    )
    assert response.status_code == 201, response.text


@pytest.fixture
def analysed(api) -> dict:
    client = api.client
    project_id = _project(client)
    _upload(client, project_id)
    started = client.post(f"/api/v1/projects/{project_id}/analysis")
    assert started.status_code == 202, started.text
    result = client.get(f"/api/v1/projects/{project_id}/analysis")
    assert result.status_code == 200, result.text
    return result.json()


# --- the job contract ------------------------------------------------------


def test_starting_analysis_returns_a_job_naming_its_kind(api):
    client = api.client
    project_id = _project(client)
    _upload(client, project_id)
    body = client.post(f"/api/v1/projects/{project_id}/analysis").json()
    assert body["kind"] == "analysis"
    assert body["status"] in {"queued", "running", "completed"}


def test_analysing_without_an_artifact_is_refused_in_the_users_terms(api):
    client = api.client
    project_id = _project(client)
    response = client.post(f"/api/v1/projects/{project_id}/analysis")
    assert response.status_code == 400
    body = response.json()
    assert "workbook" in body["message"].lower()
    assert "Traceback" not in body["message"]


def test_analysis_of_an_unknown_project_is_not_our_fault(api):
    """A missing resource is NOT_FOUND, not SYSTEM_ERROR - telling the user the
    server broke misdirects them."""
    client = api.client
    response = client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/analysis"
    )
    assert response.status_code == 404
    assert response.json()["category"] == "NOT_FOUND"


def test_fetching_analysis_before_it_runs_is_not_found(api):
    client = api.client
    assert client.get(f"/api/v1/projects/{_project(client)}/analysis").status_code == 404


# --- inventory -------------------------------------------------------------


def test_inventory_counts_the_real_workbook(analysed):
    inventory = analysed["inventory"]
    # sample.twb: 4 physical columns plus 2 calculated ones.
    assert inventory["tables"] == 1
    assert inventory["columns"] == 6
    assert inventory["calculations"] == 2
    assert inventory["visuals"] == 1
    assert inventory["dashboards"] == 1


def test_the_canonical_model_is_returned_for_the_comparison_view(analysed):
    assert analysed["model"]["source_platform"] == "tableau"


# --- complexity ------------------------------------------------------------


def test_complexity_publishes_the_formula_that_produced_it(analysed):
    """A score whose derivation a reader cannot follow is decoration."""
    complexity = analysed["complexity"]
    assert 0.0 <= complexity["score"] <= 1.0
    assert complexity["formula"], "the derivation must travel with the number"
    assert "weight" in complexity["formula"].lower()
    assert complexity["band"] in {"low", "moderate", "high"}


def test_a_workbook_of_plain_columns_is_less_complex_than_one_of_calculations(api):
    """The score must respond to what actually makes migration expensive."""
    from app.services.analysis import complexity_of
    from dashboardbridge_contracts import Inventory

    plain = complexity_of(Inventory(tables=1, columns=50))
    calcs = complexity_of(Inventory(tables=1, columns=50, calculations=40))
    assert calcs.score > plain.score


def test_an_empty_workbook_does_not_divide_by_zero(api):
    from app.services.analysis import complexity_of
    from dashboardbridge_contracts import Inventory

    assert complexity_of(Inventory()).score == 0.0


# --- compatibility ---------------------------------------------------------


def test_compatibility_totals_match_the_flags(analysed):
    compatibility = analysed["compatibility"]
    counted = (
        compatibility["converted"]
        + compatibility["partial"]
        + compatibility["ai_required"]
        + compatibility["unsupported"]
        + compatibility["failed"]
    )
    assert counted == compatibility["total"]


def test_nothing_unconvertible_is_missing_from_the_flags(analysed):
    """Every object that could not be represented must be reported. A refusal
    nobody can see is a silent drop."""
    undetermined = [
        column
        for datasource in analysed["model"]["datasources"]
        for table in datasource["tables"]
        for column in table["columns"]
        if column["expression"] and column["grain"] is None
    ]
    for column in undetermined:
        assert any(column["id"] in flag["item"] for flag in analysed["flags"])


# --- determinism -----------------------------------------------------------


def test_analysing_the_same_artifact_twice_gives_the_same_model(api):
    client = api.client
    first, second = (_project(client), _project(client))
    for project_id in (first, second):
        _upload(client, project_id)
        client.post(f"/api/v1/projects/{project_id}/analysis")
    a = client.get(f"/api/v1/projects/{first}/analysis").json()
    b = client.get(f"/api/v1/projects/{second}/analysis").json()
    assert a["model"] == b["model"]
    assert a["inventory"] == b["inventory"]
