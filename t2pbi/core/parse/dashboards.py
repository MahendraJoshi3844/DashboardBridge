"""Parse <dashboards> into Dashboard IR (name + referenced worksheet names)."""

from __future__ import annotations

from lxml import etree

from t2pbi.ir import Dashboard, Workbook


def parse_dashboards(root: etree._Element, wb: Workbook) -> None:
    for db_el in root.findall("./dashboards/dashboard"):
        name = db_el.get("name") or "Dashboard"
        sheet_names: list[str] = []
        for zone in db_el.findall(".//zone"):
            sheet = zone.get("name")
            if sheet and sheet not in sheet_names:
                sheet_names.append(sheet)
        wb.dashboards.append(Dashboard(name=name, sheet_names=sheet_names))
