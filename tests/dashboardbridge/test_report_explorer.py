"""The Report Explorer: which visuals came across, and publishing a chosen few.

Each Tableau worksheet becomes one Power BI page holding its visual. The
explorer lists them with their Tableau source, and a person ticks the visuals
to publish; nothing is ticked by default, so the .pbip carries only what was
chosen.
"""

from __future__ import annotations

import io
import json
import zipfile

from app.services import workspace as ws
from tests.dashboardbridge.test_conversion import FIXTURES
from tests.support.engines import needs_tableau

PREFIX = "/api/v1"


def _converted(client, fixture: str = "clashes.twb") -> str:
    project_id = client.post(
        f"{PREFIX}/projects",
        json={"source_platform": "tableau", "target_platform": "powerbi", "name": "Clashes"},
    ).json()["project_id"]
    client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={"file": (fixture, (FIXTURES / fixture).read_bytes(), "application/octet-stream")},
    )
    client.post(f"{PREFIX}/projects/{project_id}/analysis")
    started = client.post(f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False})
    assert started.status_code == 202, started.text
    return project_id


def _pages(archive: zipfile.ZipFile) -> dict[str, list[str]]:
    """Page id -> visual ids, read off the files in the archive."""
    names = archive.namelist()
    order_file = next(name for name in names if name.endswith("pages/pages.json"))
    order = json.loads(archive.read(order_file))["pageOrder"]
    return {
        page: sorted(
            name.split("/visuals/")[1].split("/")[0]
            for name in names
            if f"/pages/{page}/visuals/" in name and name.endswith("visual.json")
        )
        for page in order
    }


@needs_tableau
def test_the_explorer_lists_pages_visuals_and_their_tableau_source(api):
    project_id = _converted(api.client)
    report = api.client.get(f"{PREFIX}/projects/{project_id}/workspace/report").json()

    names = {page["name"] for page in report["pages"]}
    assert {"Profit by Region", "Attainment by Region"} <= names
    visual = next(v for page in report["pages"] for v in page["visuals"])
    assert visual["visual_type"]
    assert visual["source_name"] in names
    assert visual["fields"], "a written visual has fields on it"


@needs_tableau
def test_publishing_nothing_selected_carries_no_visuals(api):
    project_id = _converted(api.client)
    response = api.client.post(f"{PREFIX}/projects/{project_id}/workspace/publish", json={"visual_ids": []})
    assert response.status_code == 200, response.text
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    pages = _pages(archive)
    assert sum(len(visuals) for visuals in pages.values()) == 0
    assert len(pages) == 1, "a report keeps one page so Power BI Desktop can open it"
    assert any(name.endswith(".tmdl") for name in archive.namelist()), "the model is always carried"


@needs_tableau
def test_publishing_a_selection_carries_exactly_those_visuals(api):
    project_id = _converted(api.client)
    report = api.client.get(f"{PREFIX}/projects/{project_id}/workspace/report").json()
    chosen = next(v for page in report["pages"] for v in page["visuals"])

    response = api.client.post(
        f"{PREFIX}/projects/{project_id}/workspace/publish", json={"visual_ids": [chosen["id"]]}
    )
    pages = _pages(zipfile.ZipFile(io.BytesIO(response.content)))
    assert pages == {chosen["page_id"]: [chosen["id"]]}
    assert 'filename="Clashes.pbip.zip"' in response.headers["content-disposition"]


@needs_tableau
def test_an_unknown_visual_id_is_refused_rather_than_ignored(api):
    project_id = _converted(api.client)
    response = api.client.post(
        f"{PREFIX}/projects/{project_id}/workspace/publish", json={"visual_ids": ["nope"]}
    )
    assert response.status_code == 400


# --- the filter itself ---------------------------------------------------------


def _report_files() -> dict[str, bytes]:
    root = "R.Report/definition/pages"
    page = lambda pid, name: json.dumps({"name": pid, "displayName": name, "width": 1280, "height": 720}).encode()  # noqa: E731
    visual = lambda vid: json.dumps({"name": vid, "visual": {"visualType": "barChart"}}).encode()  # noqa: E731
    return {
        f"{root}/pages.json": json.dumps({"pageOrder": ["p1", "p2"], "activePageName": "p1"}).encode(),
        f"{root}/p1/page.json": page("p1", "One"),
        f"{root}/p1/visuals/v1/visual.json": visual("v1"),
        f"{root}/p2/page.json": page("p2", "Two"),
        f"{root}/p2/visuals/v2/visual.json": visual("v2"),
        "M.SemanticModel/definition/model.tmdl": b"model Model\n",
    }


def test_a_page_whose_visuals_are_all_unticked_is_dropped():
    kept = ws.filter_report(_report_files(), {"v2"})
    order = json.loads(kept["R.Report/definition/pages/pages.json"])
    assert order == {"pageOrder": ["p2"], "activePageName": "p2"}
    assert not any("/p1/" in name for name in kept)
    assert "M.SemanticModel/definition/model.tmdl" in kept


def test_with_nothing_ticked_one_empty_page_remains_and_says_so():
    kept = ws.filter_report(_report_files(), set())
    order = json.loads(kept["R.Report/definition/pages/pages.json"])
    assert order["pageOrder"] == ["p1"]
    page = json.loads(kept["R.Report/definition/pages/p1/page.json"])
    assert page["displayName"] == "Page 1"
    assert not any("/visuals/" in name for name in kept)
