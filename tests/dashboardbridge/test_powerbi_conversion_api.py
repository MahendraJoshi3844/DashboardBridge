"""Power BI to Tableau over the API: upload, analyse, convert, download, report.

`SPEC-powerbi-to-tableau-web.md` FR3-FR9 and AC5, AC10. The engine is tested in
`test_powerbi_to_tableau.py`; this proves the gateway carries what it returns
without adding a claim of its own.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from lxml import etree
from tests.support.engines import needs_tableau

pytestmark = needs_tableau

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pbip"
PREFIX = "/api/v1"


def _zipped(directory: Path, only: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory).as_posix()
            if path.is_file() and (only is None or relative.startswith(only)):
                archive.write(path, relative)
    return buffer.getvalue()


def _project(client, source: str = "powerbi", target: str = "tableau") -> str:
    response = client.post(
        f"{PREFIX}/projects",
        json={"source_platform": source, "target_platform": target, "name": "Retail"},
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()["project_id"]


def _analysed(client, data: bytes | None = None) -> str:
    project_id = _project(client)
    upload = client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={"file": ("Retail.zip", data or _zipped(FIXTURE), "application/zip")},
    )
    assert upload.status_code in {200, 201}, upload.text
    analysis = client.post(f"{PREFIX}/projects/{project_id}/analysis")
    assert analysis.status_code == 202, analysis.text
    return project_id


def _converted(client) -> str:
    project_id = _analysed(client)
    response = client.post(
        f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False}
    )
    assert response.status_code == 202, response.text
    return project_id


# --- analysis predicts what conversion will do ---------------------------------


def test_the_analysis_prediction_is_the_conversion_result(api):
    """Spec §7 Q2: a dry run of the same rules, so the two screens agree."""
    project_id = _converted(api.client)
    analysis = api.client.get(f"{PREFIX}/projects/{project_id}/analysis").json()
    conversion = api.client.get(f"{PREFIX}/projects/{project_id}/conversion").json()

    assert analysis["compatibility"] == conversion["compatibility"]
    assert analysis["flags"] == conversion["flags"]


def test_the_analysis_names_the_refused_measure_before_anything_is_converted(api):
    project_id = _analysed(api.client)
    analysis = api.client.get(f"{PREFIX}/projects/{project_id}/analysis").json()
    refused = [
        flag
        for flag in analysis["flags"]
        if flag["item"] == "Sales.Revenue per Unit" and flag["stage"] == "translate"
    ]
    assert len(refused) == 1
    assert refused[0]["status"] == "unsupported"
    assert "DIVIDE" in refused[0]["reason"]


def test_a_report_with_no_semantic_model_is_refused_at_analysis(api):
    """Spec §5: visuals cannot be bound without the model they read."""
    client = api.client
    project_id = _project(client)
    upload = client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={
            "file": (
                "Retail.zip",
                _zipped(FIXTURE, only="Retail.Report"),
                "application/zip",
            )
        },
    )
    assert upload.status_code in {200, 201}, upload.text
    response = client.post(f"{PREFIX}/projects/{project_id}/analysis")
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["category"] == "UNSUPPORTED_ARTIFACT"
    assert "semantic model" in body["message"]


# --- conversion and download ---------------------------------------------------


def test_the_conversion_produces_a_tableau_workbook(api):
    project_id = _converted(api.client)
    conversion = api.client.get(f"{PREFIX}/projects/{project_id}/conversion").json()
    counts = conversion["compatibility"]
    assert counts["total"] == sum(
        counts[key] for key in ("converted", "partial", "ai_required", "unsupported", "failed")
    )
    assert counts["unsupported"] >= 1


def test_the_download_is_the_twb_itself(api):
    project_id = _converted(api.client)
    response = api.client.get(f"{PREFIX}/projects/{project_id}/artifact")
    assert response.status_code == 200
    assert 'filename="Retail.twb"' in response.headers["content-disposition"]
    assert response.headers["content-type"].startswith("application/xml")
    root = etree.fromstring(response.content)
    assert root.tag == "workbook"


def test_a_tableau_to_power_bi_download_is_still_a_zip(api):
    """AC11: the other direction is unchanged."""
    from tests.dashboardbridge.test_conversion import _ready  # noqa: PLC0415

    project_id = _ready(api.client)
    api.client.post(f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False})
    response = api.client.get(f"{PREFIX}/projects/{project_id}/artifact")
    assert response.headers["content-type"] == "application/zip"


# --- verification is honest ----------------------------------------------------


def test_validation_is_unverified_and_says_why(api):
    project_id = _converted(api.client)
    started = api.client.post(f"{PREFIX}/projects/{project_id}/validation")
    assert started.status_code == 202, started.text

    validation = api.client.get(f"{PREFIX}/projects/{project_id}/validation").json()
    assert validation["verdict"] == "unverified"
    assert validation["score"] is None
    assert validation["categories"] == {}
    assert [rule["status"] for rule in validation["rules"]] == ["NOT_APPLICABLE"]
    assert "Tableau" in validation["rules"][0]["note"]


def test_the_report_names_the_direction_it_describes(api):
    project_id = _converted(api.client)
    html = api.client.get(f"{PREFIX}/projects/{project_id}/report?format=html").text
    assert "Power BI to Tableau" in html
    assert "Tableau to Power BI" not in html
