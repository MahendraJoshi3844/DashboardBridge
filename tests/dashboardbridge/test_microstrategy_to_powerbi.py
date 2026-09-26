"""MicroStrategy → Power BI: the engine adapter and the API path.

The converter itself is `mstr2pbi` (its own repository, its own 76 tests). This
file proves two things about how DashboardBridge carries it:

1. The adapter reports in contract terms without smoothing anything away, and
   honours rule 1: nothing untranslatable is emitted, not even a placeholder.
2. The gateway runs upload → analysis → conversion → download → validation for
   a `microstrategy` project exactly as it does for the other directions.

The fixture is **synthetic** (`tests/fixtures/microstrategy/retail_bundle`, the
mstr2pbi sample). AGENTS.md is right that synthetic fixtures test our reading
of a format, not the format; the first real `.mstr` file replaces it.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from dashboardbridge_contracts.enums import ConversionStatus

from engines.conversion.from_microstrategy import (
    UnreadableMicroStrategy,
    convert_microstrategy_to_powerbi,
)
from tests.dashboardbridge.test_local_only_egress import watched

BUNDLE = Path(__file__).resolve().parents[1] / "fixtures" / "microstrategy" / "retail_bundle"
PREFIX = "/api/v1"


def _package(directory: Path = BUNDLE, folder: str = "") -> bytes:
    """The bundle as one zip - how it arrives as `.mstr` or `.zip`."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.glob("*.json")):
            archive.write(path, f"{folder}{path.name}")
    return buffer.getvalue()


def _tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# --- the engine adapter ---------------------------------------------------------


def test_a_package_becomes_a_power_bi_project(tmp_path):
    outcome = convert_microstrategy_to_powerbi(_package(), tmp_path / "out", "Retail")

    assert (outcome.project_dir / "Retail.pbip").is_file()
    assert (outcome.project_dir / "Retail.SemanticModel" / "definition" / "model.tmdl").is_file()
    assert (outcome.project_dir / "Retail.Report" / "definition" / "pages" / "pages.json").is_file()
    assert outcome.model.source_platform.value == "microstrategy"
    assert outcome.model.name == "Retail"


def test_rule_1_nothing_untranslatable_is_emitted(tmp_path):
    """No `BLANK()` placeholder measure, and no measure built on a withheld one."""
    outcome = convert_microstrategy_to_powerbi(_package(), tmp_path / "out", "Retail")
    metrics = (
        outcome.project_dir / "Retail.SemanticModel" / "definition" / "tables" / "Metrics.tmdl"
    ).read_text(encoding="utf-8")

    assert "= BLANK()\n" not in metrics
    assert "measure 'Revenue Rank'" not in metrics
    assert "measure 'Rank Growth'" not in metrics  # built on Revenue Rank
    assert "measure 'Profit Margin' = DIVIDE([Profit], [Revenue])" in metrics

    held = {flag.ref for flag in outcome.flags if flag.status is ConversionStatus.UNSUPPORTED}
    assert {"metric:Revenue Rank", "metric:Rank Growth", "metric:Revenue With Tax"} <= held


def test_assumptions_are_partial_not_converted(tmp_path):
    outcome = convert_microstrategy_to_powerbi(_package(), tmp_path / "out", "Retail")
    by_ref = {flag.ref: flag for flag in outcome.flags}

    level = by_ref["metric:Region Revenue"]
    assert level.status is ConversionStatus.PARTIAL
    assert "ALLSELECTED" in level.reason or "standard filtering" in level.reason


def test_counts_are_per_object_and_sum_to_the_whole(tmp_path):
    c = convert_microstrategy_to_powerbi(_package(), tmp_path / "out", "Retail").compatibility
    assert c.converted + c.partial + c.ai_required + c.unsupported + c.failed == c.total
    assert c.ai_required == 0  # no model is consulted on this path
    assert c.converted > 0 and c.partial > 0 and c.unsupported > 0


def test_translated_measures_carry_source_and_dax(tmp_path):
    outcome = convert_microstrategy_to_powerbi(_package(), tmp_path / "out", "Retail")
    columns = {column.id: column for column in outcome.model.all_columns()}
    profit = columns["Metrics.Profit"]
    assert profit.expression.source_text == "[Revenue] - [Cost]"
    assert profit.translation.target_text == "[Revenue] - [Cost]"
    assert "Metrics.Revenue Rank" not in columns


def test_the_recording_names_what_crossed_and_what_was_held(tmp_path):
    timeline = convert_microstrategy_to_powerbi(_package(), tmp_path / "out", "Retail").timeline
    held = {event.name for event in timeline.held()}
    crossed = {event.name for event in timeline.crossed()}
    assert "Revenue Rank" in held
    assert "Profit" in crossed


def test_same_input_same_project(tmp_path):
    a = convert_microstrategy_to_powerbi(_package(), tmp_path / "a", "Retail")
    b = convert_microstrategy_to_powerbi(_package(), tmp_path / "b", "Retail")
    assert _tree(a.project_dir) == _tree(b.project_dir)
    assert a.compatibility == b.compatibility
    assert [flag.model_dump() for flag in a.flags] == [flag.model_dump() for flag in b.flags]


def test_a_package_with_nothing_recognisable_is_refused_by_name(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("thumbnail.png", b"\x89PNG")
    with pytest.raises(UnreadableMicroStrategy) as refused:
        convert_microstrategy_to_powerbi(buffer.getvalue(), tmp_path / "out", "Empty")
    assert "thumbnail.png" in str(refused.value)


def test_conversion_makes_no_network_call(tmp_path, monkeypatch):
    """The offline promise, for this direction too (`P7.8`)."""
    with watched(monkeypatch) as seen:
        convert_microstrategy_to_powerbi(_package(), tmp_path / "out", "Retail")
    assert seen == []


# --- through the gateway --------------------------------------------------------


def _project(client) -> str:
    response = client.post(
        f"{PREFIX}/projects",
        json={"source_platform": "microstrategy", "target_platform": "powerbi", "name": "Retail"},
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()["project_id"]


def _upload(client, project_id: str, filename: str, data: bytes):
    return client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={"file": (filename, data, "application/octet-stream")},
    )


@pytest.mark.parametrize("filename", ["Retail.mstr", "Retail.zip"])
def test_upload_analyse_convert_download_validate(api, filename):
    client = api.client
    project_id = _project(client)
    upload = _upload(client, project_id, filename, _package(folder="retail_bundle/"))
    assert upload.status_code == 201, upload.text
    assert upload.json()["detected_platform"] == "microstrategy"

    assert client.post(f"{PREFIX}/projects/{project_id}/analysis").status_code == 202
    analysis = client.get(f"{PREFIX}/projects/{project_id}/analysis").json()
    assert analysis["inventory"]["calculations"] > 0
    assert analysis["inventory"]["dashboards"] > 0

    converted = client.post(f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False})
    assert converted.status_code == 202, converted.text
    conversion = client.get(f"{PREFIX}/projects/{project_id}/conversion").json()
    assert conversion["compatibility"] == analysis["compatibility"]

    download = client.get(f"{PREFIX}/projects/{project_id}/artifact")
    assert download.status_code == 200
    assert download.headers["content-disposition"].endswith('.pbip.zip"')
    names = zipfile.ZipFile(io.BytesIO(download.content)).namelist()
    assert "Retail.pbip" in names
    assert "migration_report.html" in names

    validated = client.post(f"{PREFIX}/projects/{project_id}/validation")
    assert validated.status_code == 202, validated.text


def test_a_zip_that_is_not_a_microstrategy_export_is_refused(api):
    client = api.client
    project_id = _project(client)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("holiday/photo.jpg", b"\xff\xd8")
    response = _upload(client, project_id, "Photos.zip", buffer.getvalue())
    assert response.status_code == 400
    assert "MicroStrategy" in response.json()["message"]


def test_an_mstr_that_is_not_an_archive_is_refused(api):
    client = api.client
    project_id = _project(client)
    response = _upload(client, project_id, "Fake.mstr", b"not a package at all")
    assert response.status_code == 400


def test_a_microstrategy_package_is_refused_by_a_tableau_project(api):
    client = api.client
    response = client.post(
        f"{PREFIX}/projects",
        json={"source_platform": "tableau", "target_platform": "powerbi", "name": "T"},
    )
    project_id = response.json()["project_id"]
    refused = _upload(client, project_id, "Retail.mstr", _package())
    assert refused.status_code == 400


def test_validation_matches_visuals_on_their_dossier_pages(api):
    """A dossier page holds several visuals; validation looks for them there,
    not for a page per visual as it does for Tableau worksheets."""
    client = api.client
    project_id = _project(client)
    assert _upload(client, project_id, "Retail.mstr", _package()).status_code == 201
    client.post(f"{PREFIX}/projects/{project_id}/analysis")
    client.post(f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False})
    assert client.post(f"{PREFIX}/projects/{project_id}/validation").status_code == 202
    rules = client.get(f"{PREFIX}/projects/{project_id}/validation").json()["rules"]

    by_id: dict[str, list[str]] = {}
    for rule in rules:
        by_id.setdefault(rule["rule_id"], []).append(rule["status"])
    assert by_id["DASHBOARD_COUNT_MATCH"] == ["PASS"]
    assert by_id["VISUAL_COUNT_MATCH"] == ["PASS"]
    assert set(by_id["VISUAL_TYPE_PRESENT"]) == {"PASS"}
    # Titles are honestly not written yet - a warning, never a pass.
    assert set(by_id["VISUAL_TITLE_CARRIED"]) == {"WARNING"}


def test_validation_reads_relationships_file_and_measure_bindings(tmp_path):
    """Two gaps in the PBIP reader that only a multi-visual, measure-heavy
    project exposed: relationships.tmdl was never read, and a visual bound to a
    measure looked like a binding to a column named ''."""
    from engines.validation.target import TargetProject

    outcome = convert_microstrategy_to_powerbi(_package(), tmp_path / "out", "Retail")
    target = TargetProject.from_dir(outcome.project_dir)
    assert len(target.semantic_model().relationships) == len(outcome.model.relationships) > 0
    bindings = [b for page in target.report().pages for v in page.visuals for b in v.bindings]
    assert bindings and all(b.column for b in bindings)
    assert any(b.table == "Metrics" and b.column == "Revenue" for b in bindings)
