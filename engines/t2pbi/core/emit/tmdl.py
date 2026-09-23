"""Build TMDL text for the semantic model from the IR."""

from __future__ import annotations

import hashlib
import re

from engines.t2pbi.core.emit.datatypes import m_datatype, tmdl_datatype
from engines.t2pbi.ir import Severity, Table, Workbook

_ILLEGAL = re.compile(r"[\r\n\"']")


def sanitize_name(name: str) -> str:
    """Make a name safe for TMDL identifiers. Returns the cleaned name."""
    cleaned = _ILLEGAL.sub("", name).strip()
    return cleaned or "Unnamed"


def _quote(name: str) -> str:
    return f"'{sanitize_name(name)}'"


def _m_identifier(name: str) -> str:
    """Quote a column name for use inside an M ``type table [...]`` record."""
    return '#"' + sanitize_name(name).replace('"', "") + '"'


def _partition_tmdl(table: Table) -> list[str]:
    """A typed, empty Power Query partition so the model loads with the right schema.

    We never read a Tableau extract and cannot know the real connection, so the
    honest output is a correctly-typed empty query the user repoints at their
    source. A table with no partition at all makes Power BI reject the model.
    """
    fields = ", ".join(
        f"{_m_identifier(col.display_name)} = {m_datatype(col.datatype)}"
        for col in table.columns
        if not col.is_calculated
    )
    source = f"let Source = #table(type table [{fields}], {{}}) in Source"
    return [
        f"\tpartition {_quote(table.name)} = m",
        "\t\tmode: import",
        f"\t\tsource = {source}",
        "",
    ]


def emitted_columns(table: Table) -> dict[str, str]:
    """Every name TMDL will actually write for this table, and what it writes it as.

    Keyed by every name a shelf might have used - the internal `name` and the
    `caption` - and valued with the single display name the file carries. A
    calculated column whose translation was refused has no DAX and appears
    nowhere here, which is the point: it is not in the model, so nothing may
    point at it.

    `table_tmdl` below is the only other place that decides what is written, and
    it must keep agreeing with this. Two independent answers to "is this column
    in the model" is how a report ends up referencing one that is not.
    """
    emitted: dict[str, str] = {}
    for col in table.columns:
        if col.is_calculated and not col.dax:
            continue
        for key in (col.name, col.caption):
            if key:
                emitted.setdefault(key, col.display_name)
    return emitted


def table_tmdl(
    table: Table, workbook: Workbook | None = None, datasource: str | None = None
) -> str:
    """Render a single table's TMDL definition (deterministic ordering)."""
    lines: list[str] = [f"table {_quote(table.name)}", ""]

    for col in table.columns:
        if col.is_calculated:
            continue  # calculated -> column/measure below (only if DAX succeeded)
        display = col.caption or col.name
        lines.append(f"\tcolumn {_quote(display)}")
        lines.append(f"\t\tdataType: {tmdl_datatype(col.datatype)}")
        lines.append(f"\t\tsourceColumn: {sanitize_name(col.name)}")
        lines.append("")

    # Row-level calcs become calculated columns; only aggregate calcs are measures.
    # Emitting a row-level expression as a measure yields DAX that will not validate.
    for col in table.columns:
        if col.is_calculated and col.dax and not col.is_aggregate:
            lines.append(f"\tcolumn {_quote(col.display_name)} = {col.dax}")
            lines.append(f"\t\tdataType: {tmdl_datatype(col.datatype)}")
            lines.append("")

    for col in table.columns:
        if col.is_calculated and col.dax and col.is_aggregate:
            lines.append(f"\tmeasure {_quote(col.display_name)} = {col.dax}")
            lines.append("")

    lines.extend(_partition_tmdl(table))

    if workbook is not None:
        origin = f" ({datasource})" if datasource else ""
        workbook.add_flag(
            item=f"{table.name}{origin}",
            severity=Severity.MANUAL,
            reason=(
                "Table is emitted with the correct schema but an empty query: "
                "point its Power Query source at your real data."
            ),
            stage="emit",
        )

    return "\n".join(lines).rstrip() + "\n"


def model_tmdl(table_names: list[str], culture: str = "en-US") -> str:
    lines = ["model Model", f"\tculture: {culture}", "\tdefaultPowerBIDataSourceVersion: powerBI_V3", ""]
    for name in table_names:
        lines.append(f"ref table {_quote(name)}")
    return "\n".join(lines).rstrip() + "\n"


def _rel_id(rel) -> str:
    seed = f"{rel.from_table}|{rel.from_column}|{rel.to_table}|{rel.to_column}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def relationships_tmdl(relationships: list) -> str:
    """Render model-level relationships (deterministic ids and ordering)."""
    blocks: list[str] = []
    for rel in sorted(
        relationships, key=lambda r: (r.from_table, r.from_column, r.to_table)
    ):
        from_ref = f"{_quote(rel.from_table)}.{_quote(rel.from_column)}"
        to_ref = f"{_quote(rel.to_table)}.{_quote(rel.to_column)}"
        block = [
            f"relationship {_rel_id(rel)}",
            f"\tfromColumn: {from_ref}",
            f"\ttoColumn: {to_ref}",
        ]
        if rel.kind == "many_to_many":
            block.append("\tfromCardinality: many")
            block.append("\ttoCardinality: many")
        blocks.append("\n".join(block))
    return ("\n\n".join(blocks) + "\n") if blocks else ""
