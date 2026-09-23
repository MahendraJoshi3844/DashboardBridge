"""Parse the internal <datasource name='Parameters'> into Parameter IR.

Tableau parameters become Power BI what-if parameters. We capture the domain
(range bounds/step or list members) so the emitter can build a proper what-if
table instead of hardcoding the value into DAX.
"""

from __future__ import annotations

from lxml import etree

from engines.t2pbi.ir import Parameter, Workbook


def _clean_name(raw: str | None) -> str:
    if not raw:
        return ""
    return raw.strip().lstrip("[").rstrip("]")


def parse_parameters(root: etree._Element, wb: Workbook) -> None:
    ds = root.find("./datasources/datasource[@name='Parameters']")
    if ds is None:
        return
    for col in ds.findall("./column"):
        name = _clean_name(col.get("name"))
        if not name:
            continue
        caption = col.get("caption") or name
        kind = "list" if col.get("param-domain-type") == "list" else "range"

        rng = col.find("./range")
        members = [
            m.get("value") for m in col.findall("./members/member") if m.get("value")
        ]

        wb.parameters.append(
            Parameter(
                name=name,
                caption=caption,
                datatype=col.get("datatype") or "string",
                default_value=col.get("value") or "",
                kind=kind,
                min_value=rng.get("min") if rng is not None else None,
                max_value=rng.get("max") if rng is not None else None,
                step=rng.get("granularity") if rng is not None else None,
                members=members,
            )
        )
