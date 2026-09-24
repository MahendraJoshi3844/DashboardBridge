"""The workspace: reading the produced project and saving hand edits as versions."""

from __future__ import annotations

import io
import zipfile

from app.services import workspace as ws
from dashboardbridge_contracts import WorkspaceEdit
from tests.dashboardbridge.test_conversion import _ready

PREFIX = "/api/v1"


def _converted(client) -> str:
    project_id = _ready(client)
    started = client.post(f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False})
    assert started.status_code == 202, started.text
    return project_id


def test_the_workspace_reads_tables_measures_and_power_query(api):
    project_id = _converted(api.client)
    model = api.client.get(f"{PREFIX}/projects/{project_id}/workspace").json()

    assert model["version"] == 0
    assert [version["note"] for version in model["versions"]] == ["Converted"]
    sales = next(table for table in model["tables"] if table["name"] == "Sales")
    assert any(measure["name"] == "Profit Ratio" for measure in sales["measures"])
    assert sales["partitions"][0]["expression"].startswith("let")
    assert any(path.endswith(".tmdl") for path in (f["path"] for f in model["files"]))


def test_a_saved_edit_is_a_new_version_and_is_what_downloads(api):
    client = api.client
    project_id = _converted(client)
    saved = client.post(
        f"{PREFIX}/projects/{project_id}/workspace/versions",
        json={
            "base_version": 0,
            "note": "Rounded the ratio",
            "edits": [
                {
                    "kind": "measure",
                    "table": "Sales",
                    "name": "Profit Ratio",
                    "expression": "ROUND(SUM('Sales'[Sales]) / SUM('Sales'[Quantity]), 2)",
                }
            ],
        },
    )
    assert saved.status_code == 201, saved.text
    model = saved.json()
    assert model["version"] == 1
    assert model["versions"][1]["note"] == "Rounded the ratio"

    archive = zipfile.ZipFile(io.BytesIO(client.get(f"{PREFIX}/projects/{project_id}/artifact").content))
    tmdl = next(
        archive.read(name).decode()
        for name in archive.namelist()
        if name.endswith("tables/Sales.tmdl")
    )
    assert "ROUND(SUM('Sales'[Sales])" in tmdl


def test_a_save_on_a_stale_version_is_refused(api):
    client = api.client
    project_id = _converted(client)
    body = {
        "base_version": 0,
        "edits": [{"kind": "measure", "table": "Sales", "name": "X", "expression": "1"}],
    }
    assert client.post(f"{PREFIX}/projects/{project_id}/workspace/versions", json=body).status_code == 201
    stale = client.post(f"{PREFIX}/projects/{project_id}/workspace/versions", json=body)
    assert stale.status_code == 409


def test_an_edit_to_a_table_that_does_not_exist_changes_nothing(api):
    client = api.client
    project_id = _converted(client)
    refused = client.post(
        f"{PREFIX}/projects/{project_id}/workspace/versions",
        json={
            "base_version": 0,
            "edits": [{"kind": "measure", "table": "Ghost", "name": "X", "expression": "1"}],
        },
    )
    assert refused.status_code == 400
    assert client.get(f"{PREFIX}/projects/{project_id}/workspace").json()["version"] == 0


# --- the text edits themselves -------------------------------------------------

_TMDL = (
    "table 'Sales'\n\n"
    "\tcolumn 'Sales'\n\t\tdataType: double\n\t\tsourceColumn: Sales\n\n"
    "\tmeasure 'Total' = SUM('Sales'[Sales])\n\n"
    "\tpartition 'Sales' = m\n\t\tmode: import\n\t\tsource = let Source = 1 in Source\n"
)


def _files() -> dict[str, bytes]:
    return {"M.SemanticModel/definition/tables/Sales.tmdl": _TMDL.encode()}


def test_a_multi_line_measure_round_trips():
    edit = WorkspaceEdit(kind="measure", table="Sales", name="Total", expression="VAR a = 1\nRETURN a")
    tables = ws.read_tables(ws.apply_edits(_files(), [edit]))
    assert tables[0].measures[0].expression == "VAR a = 1\nRETURN a"


def test_a_multi_line_power_query_round_trips():
    query = 'let\n    Source = Sql.Database("server", "db")\nin\n    Source'
    edit = WorkspaceEdit(kind="partition", table="Sales", name="Sales", expression=query)
    tables = ws.read_tables(ws.apply_edits(_files(), [edit]))
    assert tables[0].partitions[0].expression == query
    assert tables[0].partitions[0].mode == "import"


def test_a_new_measure_is_added_before_the_partition():
    edit = WorkspaceEdit(kind="measure", table="Sales", name="Held one", expression="1")
    text = ws.apply_edits(_files(), [edit])["M.SemanticModel/definition/tables/Sales.tmdl"].decode()
    assert text.index("'Held one'") < text.index("partition")
    assert [m.name for m in ws.read_tables({"a/definition/tables/S.tmdl": text.encode()})[0].measures] == [
        "Total",
        "Held one",
    ]


def test_a_held_calculation_written_by_hand_is_no_longer_held(api):
    from tests.dashboardbridge.test_conversion import FIXTURES  # noqa: PLC0415

    client = api.client
    project_id = client.post(
        f"{PREFIX}/projects",
        json={"source_platform": "tableau", "target_platform": "powerbi", "name": "Clashes"},
    ).json()["project_id"]
    client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={"file": ("clashes.twb", (FIXTURES / "clashes.twb").read_bytes(), "application/octet-stream")},
    )
    client.post(f"{PREFIX}/projects/{project_id}/analysis")
    client.post(f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False})

    held = client.get(f"{PREFIX}/projects/{project_id}/workspace").json()["held"]
    assert held, "clashes.twb has calculations the converter refuses"
    first = held[0]
    saved = client.post(
        f"{PREFIX}/projects/{project_id}/workspace/versions",
        json={
            "base_version": 0,
            "edits": [{"kind": "measure", "table": first["table"], "name": first["name"], "expression": "1"}],
        },
    ).json()
    assert first["item"] not in [entry["item"] for entry in saved["held"]]


def test_a_calculated_table_is_not_reported_as_power_query():
    text = "table 'Growth'\n\n\tpartition 'Growth' = calculated\n\t\tmode: import\n\t\tsource = GENERATESERIES(0, 1, 0.01)\n"
    [table] = ws.read_tables({"m/definition/tables/Growth.tmdl": text.encode()})
    assert table.partitions[0].source_kind == "calculated"
    assert table.partitions[0].expression == "GENERATESERIES(0, 1, 0.01)"
