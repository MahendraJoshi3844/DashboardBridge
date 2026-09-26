"""Qlik -> Power BI: the engine adapter and the API path.

The converter is `qlik2pbi` (its own repository and tests). This file proves how
DashboardBridge carries it: contract terms, rule 1 (nothing untranslatable
emitted, not even a placeholder), and upload -> analyse -> convert -> download ->
validate for a `qlik` project.

The fixture is **synthetic** (`tests/fixtures/qlik/sales_app`, a `qlik app
unbuild` folder); the first real app replaces it.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("qlik2pbi", reason="optional engine not installed on this deployment")
from dashboardbridge_contracts.enums import ConversionStatus

from engines.conversion.from_qlik import UnreadableQlik, convert_qlik_to_powerbi
from tests.dashboardbridge.test_local_only_egress import watched

APP = Path(__file__).resolve().parents[1] / "fixtures" / "qlik" / "sales_app"
PREFIX = "/api/v1"
NAME = "Sales"


def _zipped(folder: str = "sales_app/") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(APP.rglob("*")):
            if path.is_file():
                archive.write(path, folder + path.relative_to(APP).as_posix())
    return buffer.getvalue()


def _script() -> bytes:
    return (APP / "script.qvs").read_bytes()


def _tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# --- the engine adapter -----------------------------------------------------------


def test_an_unbuild_zip_becomes_a_power_bi_project(tmp_path):
    outcome = convert_qlik_to_powerbi(_zipped(), tmp_path / "out", NAME)
    assert (outcome.project_dir / f"{NAME}.pbip").is_file()
    assert (outcome.project_dir / f"{NAME}.SemanticModel" / "definition" / "tables" / "Orders.tmdl").is_file()
    assert (outcome.project_dir / f"{NAME}.Report" / "definition" / "pages" / "pages.json").is_file()
    assert outcome.model.source_platform.value == "qlik"


def test_a_load_script_alone_converts_the_data_model(tmp_path):
    outcome = convert_qlik_to_powerbi(_script(), tmp_path / "out", NAME)
    tables = {t.name for t in outcome.model.all_tables()}
    assert {"Orders", "Customers", "Products"} <= tables
    assert not outcome.model.dashboards  # a script has no sheets


def test_rule_1_nothing_untranslatable_is_emitted(tmp_path):
    outcome = convert_qlik_to_powerbi(_zipped(), tmp_path / "out", NAME)
    measures = (outcome.project_dir / f"{NAME}.SemanticModel" / "definition" / "tables" / "Measures.tmdl").read_text(encoding="utf-8")
    assert "= BLANK()\n" not in measures
    assert "measure 'Running Sales'" not in measures
    assert "measure 'Total Sales' = SUM('Orders'[SalesAmount])" in measures
    held = {f.ref for f in outcome.flags if f.status is ConversionStatus.UNSUPPORTED}
    assert "master measure:Running Sales" in held
    assert "table:Budget" in held  # QVD source: columns kept, empty query


def test_tiers_become_statuses_and_counts_sum(tmp_path):
    outcome = convert_qlik_to_powerbi(_zipped(), tmp_path / "out", NAME)
    by_ref = {f.ref: f for f in outcome.flags}
    assert by_ref["master measure:Share of Total"].status is ConversionStatus.PARTIAL
    c = outcome.compatibility
    assert c.converted + c.partial + c.ai_required + c.unsupported + c.failed == c.total
    assert c.ai_required == 0 and c.converted and c.partial and c.unsupported


def test_measures_carry_qlik_source_and_dax(tmp_path):
    outcome = convert_qlik_to_powerbi(_zipped(), tmp_path / "out", NAME)
    cols = {c.id: c for c in outcome.model.all_columns()}
    sales = cols["Measures.Sales CY"]
    assert "$(vCurrentYear)" in sales.expression.source_text
    assert sales.translation.target_text == "CALCULATE(SUM('Orders'[SalesAmount]), 'Orders'[OrderYear] = 2024)"


def test_the_recording_names_what_crossed_and_what_was_held(tmp_path):
    timeline = convert_qlik_to_powerbi(_zipped(), tmp_path / "out", NAME).timeline
    assert "Running Sales" in {e.name for e in timeline.held()}
    assert "Total Sales" in {e.name for e in timeline.crossed()}


def test_same_input_same_project(tmp_path):
    a = convert_qlik_to_powerbi(_zipped(), tmp_path / "a", NAME)
    b = convert_qlik_to_powerbi(_zipped(), tmp_path / "b", NAME)
    assert _tree(a.project_dir) == _tree(b.project_dir)
    assert [f.model_dump() for f in a.flags] == [f.model_dump() for f in b.flags]


def test_nothing_recognisable_is_refused_by_name(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes/readme.txt", "hello")
    with pytest.raises(UnreadableQlik):
        convert_qlik_to_powerbi(buffer.getvalue(), tmp_path / "out", "Empty")


def test_conversion_makes_no_network_call(tmp_path, monkeypatch):
    with watched(monkeypatch) as seen:
        convert_qlik_to_powerbi(_zipped(), tmp_path / "out", NAME)
    assert seen == []


# --- through the gateway ------------------------------------------------------------


def _project(client, source: str = "qlik") -> str:
    response = client.post(f"{PREFIX}/projects",
                           json={"source_platform": source, "target_platform": "powerbi", "name": NAME})
    assert response.status_code in {200, 201}, response.text
    return response.json()["project_id"]


def _upload(client, project_id: str, filename: str, data: bytes):
    return client.post(f"{PREFIX}/projects/{project_id}/artifacts",
                       files={"file": (filename, data, "application/octet-stream")})


@pytest.mark.parametrize("filename, data", [("Sales.zip", _zipped()), ("script.qvs", _script())])
def test_upload_analyse_convert_download_validate(api, filename, data):
    client = api.client
    project_id = _project(client)
    upload = _upload(client, project_id, filename, data)
    assert upload.status_code == 201, upload.text
    assert upload.json()["detected_platform"] == "qlik"

    assert client.post(f"{PREFIX}/projects/{project_id}/analysis").status_code == 202
    analysis = client.get(f"{PREFIX}/projects/{project_id}/analysis").json()
    assert analysis["inventory"]["tables"] > 0

    assert client.post(f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False}).status_code == 202
    conversion = client.get(f"{PREFIX}/projects/{project_id}/conversion").json()
    assert conversion["compatibility"] == analysis["compatibility"]

    download = client.get(f"{PREFIX}/projects/{project_id}/artifact")
    assert download.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(download.content)).namelist()
    assert f"{NAME}.pbip" in names and "migration_report.html" in names

    assert client.post(f"{PREFIX}/projects/{project_id}/validation").status_code == 202


def test_validation_matches_visuals_on_their_sheets(api):
    client = api.client
    project_id = _project(client)
    assert _upload(client, project_id, "Sales.zip", _zipped()).status_code == 201
    client.post(f"{PREFIX}/projects/{project_id}/analysis")
    client.post(f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False})
    client.post(f"{PREFIX}/projects/{project_id}/validation")
    rules = client.get(f"{PREFIX}/projects/{project_id}/validation").json()["rules"]
    by_id: dict[str, set[str]] = {}
    for rule in rules:
        by_id.setdefault(rule["rule_id"], set()).add(rule["status"])
    assert by_id["DASHBOARD_COUNT_MATCH"] == {"PASS"}
    assert by_id["VISUAL_TYPE_PRESENT"] == {"PASS"}


def test_qvf_and_qvw_are_refused_with_the_export_route(api):
    client = api.client
    project_id = _project(client)
    for name in ("Sales.qvf", "Sales.qvw"):
        response = _upload(client, project_id, name, b"\x00binary")
        assert response.status_code == 400
        assert "unbuild" in response.json()["message"] or "-prj" in response.json()["message"]


def test_a_zip_that_is_not_a_qlik_export_is_refused(api):
    client = api.client
    project_id = _project(client)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("photos/a.jpg", b"\xff\xd8")
    response = _upload(client, project_id, "Photos.zip", buffer.getvalue())
    assert response.status_code == 400
    assert "Qlik" in response.json()["message"]


def test_a_text_file_that_is_not_a_script_is_refused(api):
    client = api.client
    project_id = _project(client)
    assert _upload(client, project_id, "notes.qvs", b"just some notes, nothing to load").status_code == 400


def test_a_qlik_export_is_refused_by_a_microstrategy_project(api):
    client = api.client
    project_id = _project(client, source="microstrategy")
    assert _upload(client, project_id, "Sales.zip", _zipped()).status_code == 400
