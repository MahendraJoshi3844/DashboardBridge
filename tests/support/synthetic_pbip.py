"""A zipped Power BI project of a stated size, generated deterministically.

The Power BI counterpart of `synthetic.py`, for the same reason: the hand-written
fixture in `tests/fixtures/pbip` is two tables and one visual, and a performance
budget measured against that says nothing.

**It is not a real project.** Nothing here came out of Power BI Desktop, so it
shows how the pipeline behaves at size and nothing about whether the reader
handles what Desktop writes - the hand-written fixture does that.

Shaped so the run is not all happy path: every fourth measure uses `DIVIDE`,
which the DAX to Tableau rules refuse, and every visual carries a tooltip field
the writer does not place.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass


@dataclass(frozen=True)
class Shape:
    tables: int = 5
    columns_per_table: int = 12
    measures: int = 25
    visuals: int = 20
    visuals_per_page: int = 4


TYPICAL = Shape()


def _table(index: int, shape: Shape) -> str:
    name = f"T{index}"
    lines = [f"table {name}", f"\tlineageTag: t{index}", ""]
    for column in range(shape.columns_per_table):
        kind = "double" if column % 3 == 0 else "string"
        lines += [
            f"\tcolumn C{column}",
            f"\t\tdataType: {kind}",
            f"\t\tsourceColumn: C{column}",
            "",
        ]
    if index == 0:
        for measure in range(shape.measures):
            formula = (
                f"DIVIDE(SUM({name}[C0]), SUM({name}[C3]))"
                if measure % 4 == 3
                else f"SUM({name}[C{(measure % 4) * 3}])"
            )
            lines += [f"\tmeasure M{measure} = {formula}", ""]
    return "\n".join(lines) + "\n"


def _visual(index: int) -> dict:
    def projection(kind: str, prop: str) -> dict:
        return {
            "field": {
                kind: {"Expression": {"SourceRef": {"Entity": "T0"}}, "Property": prop}
            }
        }

    return {
        "name": f"v{index}",
        "visual": {
            "visualType": "clusteredColumnChart" if index % 2 else "lineChart",
            "query": {
                "queryState": {
                    "Category": {"projections": [projection("Column", "C1")]},
                    "Y": {"projections": [projection("Measure", f"M{index % 3}")]},
                    "Tooltips": {"projections": [projection("Column", "C2")]},
                }
            },
        },
    }


def project_zip(shape: Shape = TYPICAL, name: str = "Synthetic") -> bytes:
    files: dict[str, str] = {
        f"{name}.pbip": json.dumps({"version": "1.0", "artifacts": [{"report": {"path": f"{name}.Report"}}]}),
        f"{name}.SemanticModel/definition.pbism": json.dumps({"version": "4.0"}),
        f"{name}.SemanticModel/definition/model.tmdl": "model Model\n",
        f"{name}.Report/definition.pbir": json.dumps({"version": "4.0"}),
    }
    for index in range(shape.tables):
        files[f"{name}.SemanticModel/definition/tables/T{index}.tmdl"] = _table(index, shape)

    pages = []
    for visual in range(shape.visuals):
        page = f"p{visual // shape.visuals_per_page}"
        if page not in pages:
            pages.append(page)
            files[f"{name}.Report/definition/pages/{page}/page.json"] = json.dumps(
                {"name": page, "displayName": f"Page {page}"}
            )
        files[f"{name}.Report/definition/pages/{page}/visuals/v{visual}/visual.json"] = (
            json.dumps(_visual(visual))
        )
    files[f"{name}.Report/definition/pages/pages.json"] = json.dumps({"pageOrder": pages})

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0))
            archive.writestr(info, files[path])
    return buffer.getvalue()
