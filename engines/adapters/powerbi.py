"""Read a Power BI project (PBIP) into the canonical model (`P6a.1`).

TMDL and PBIR, in the other direction from everything before it. Nothing here
converts: reading is a separate capability from writing (ADR-005), and this
adapter answers one question — what is in this project?

## Why this is a third TMDL parser

`engines/validation/target.py` already reads TMDL, and shares no code with the
emitter on purpose: a check that asks the writer what it wrote proves only that
the writer is self-consistent. This one is a *reader*, and needs different
depth — expressions, datatypes, hierarchies, report bindings — where the
validator needs existence and counts. Merging them would hand the validator this
parser's blind spots, which is the one thing a validator must not inherit.

## What it does not do

It does not understand DAX. Every expression is carried across verbatim, with
`translation` left empty, because `P6a.2` is where an expression stops being a
string. A `translation` written here would be an equivalence nobody computed.

TMDL has more in it than this reads — `variation`, `annotation`, `lineageTag`,
formatting, perspectives, roles. They are skipped rather than half-read: a
partial rendering of something we do not carry is worse than an honest absence,
because it looks like the thing was handled.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from dashboardbridge_contracts import (
    CanonicalModel,
    Column,
    DataSource,
    Dashboard,
    Expression,
    FieldRef,
    Relationship,
    Table,
    Visual,
    VisualBinding,
)
from dashboardbridge_contracts.enums import (
    BindingRole,
    DataType,
    Grain,
    Platform,
)

#: `table 'Quoted Name'` or `table Bare`. TMDL quotes a name only when it must,
#: and a parser that handles one form silently reads half a model.
_TABLE = re.compile(r"^table\s+(?:'([^']*)'|(\S+))\s*$")
#: `\tcolumn 'X'`, `\tcolumn X`, either optionally followed by `= expression`.
_ITEM = re.compile(
    r"^\t(column|measure)\s+(?:'([^']*)'|([^\s=]+))\s*(?:=\s*(.*))?$"
)
_DATATYPE = re.compile(r"^\t\tdataType:\s*(\S+)\s*$")
_RELATIONSHIP = re.compile(r"^relationship\s+(\S+)\s*$")
#: `\tfromColumn: Table.'Column'`, either side optionally quoted.
_REL_COLUMN = re.compile(
    r"^\t(from|to)Column:\s*(?:'([^']*)'|([^.\s]+))\.(?:'([^']*)'|(\S+))\s*$"
)
_CROSS_FILTER = re.compile(r"^\tcrossFilteringBehavior:\s*(\S+)\s*$")

#: TMDL's types, in the canonical model's words.
_DATATYPES = {
    "string": DataType.STRING,
    "int64": DataType.INTEGER,
    "double": DataType.DECIMAL,
    "decimal": DataType.DECIMAL,
    "boolean": DataType.BOOLEAN,
    "datetime": DataType.DATETIME,
    "date": DataType.DATE,
}

#: A visual's wells. The well a field sits in *is* its role, which is why the
#: canonical model has roles rather than a field per well.
_ROLES = {
    "category": BindingRole.CATEGORY,
    "y": BindingRole.VALUE,
    "y2": BindingRole.VALUE,
    "values": BindingRole.VALUE,
    "series": BindingRole.SERIES,
    "legend": BindingRole.SERIES,
    "tooltips": BindingRole.TOOLTIP,
}


@dataclass
class PBIPProject:
    """The parse-time structure: files, decoded but not yet canonical.

    Mutable and shallow, for the same reason the Tableau side has an IR - the
    canonical model is frozen, so parsing needs somewhere to build.
    """

    name: str = "Model"
    tables: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)


class PowerBIAdapter:
    """Reads PBIP. Writing is `t2pbi/core/emit` and stays there."""

    platform = Platform.POWERBI

    # ---- detect -----------------------------------------------------------

    def detect(self, data: bytes) -> bool:
        """A zipped project. Peeks at the member list, never extracts.

        Extracting to find out what something is means extracting whatever an
        attacker sent (`P7.3`).
        """
        if data[:2] != b"PK":
            return False
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
        except zipfile.BadZipFile:
            return False
        return any(name.endswith((".pbip", ".pbism", ".pbir")) for name in names)

    def detects(self, directory: str | Path) -> bool:
        """The same question for a project on disk."""
        root = Path(directory)
        if not root.is_dir():
            return False
        return any(root.glob("*.pbip")) or any(root.glob("*/definition.pbism"))

    # ---- read -------------------------------------------------------------

    def read(self, directory: str | Path) -> CanonicalModel:
        root = Path(directory)
        files = {
            str(path.relative_to(root)).replace("\\", "/"): path.read_text(
                encoding="utf-8", errors="replace"
            )
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.suffix in {".tmdl", ".json", ".pbip", ".pbism", ".pbir"}
        }
        return self.normalize(self._project(files, root.name))

    def parse(self, data: bytes) -> PBIPProject:
        """A zipped project to the parse-time structure."""
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = {
                name: archive.read(name).decode("utf-8", errors="replace")
                for name in sorted(archive.namelist())
                if name.endswith((".tmdl", ".json", ".pbip", ".pbism", ".pbir"))
            }
        return self._project(files, "Model")

    def normalize(self, parsed: PBIPProject) -> CanonicalModel:
        tables = [
            Table(
                id=table["name"],
                name=table["name"],
                columns=[_column(table["name"], item) for item in table["items"]],
            )
            for table in parsed.tables
        ]
        return CanonicalModel(
            source_platform=Platform.POWERBI,
            name=parsed.name,
            # One datasource: a semantic model is the source, and inventing
            # several from partitions would report a structure Power BI does
            # not have.
            datasources=[DataSource(id="model", name=parsed.name, tables=tables)],
            relationships=[_relationship(row) for row in parsed.relationships],
            visuals=[
                visual for page in parsed.pages for visual in page["visuals"]
            ],
            dashboards=[
                Dashboard(
                    id=page["id"],
                    name=page["name"],
                    visual_ids=[visual.id for visual in page["visuals"]],
                )
                for page in parsed.pages
            ],
        )

    # ---- the files --------------------------------------------------------

    def _project(self, files: Mapping[str, str], fallback: str) -> PBIPProject:
        project = PBIPProject(name=_model_name(files, fallback))
        for path, text in files.items():
            if "/definition/tables/" in path and path.endswith(".tmdl"):
                table = _parse_table(text)
                if table is not None:
                    project.tables.append(table)
            elif path.endswith("relationships.tmdl"):
                project.relationships.extend(_parse_relationships(text))
        project.tables.sort(key=lambda table: table["name"])
        project.pages = _parse_pages(files)
        return project


# --- TMDL --------------------------------------------------------------------


def _unquote(*candidates: str | None) -> str:
    """The first group that matched. TMDL quotes optionally, so each name has
    two possible capture groups and exactly one of them is set."""
    for value in candidates:
        if value:
            return value
    return ""


def _parse_table(body: str) -> dict | None:
    name = ""
    items: list[dict] = []
    lines = body.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        table = _TABLE.match(line)
        if table:
            name = _unquote(table.group(1), table.group(2))
            index += 1
            continue

        item = _ITEM.match(line)
        if item:
            kind = item.group(1)
            expression = (item.group(4) or "").strip()
            if expression.startswith("```"):
                # Desktop writes a long expression in a fenced block. Reading
                # only the first line truncates it into something that still
                # looks like valid DAX, which is the worst possible outcome.
                expression, index = _fenced(lines, index)
            items.append(
                {
                    "kind": kind,
                    "name": _unquote(item.group(2), item.group(3)),
                    "expression": expression,
                    "datatype": _datatype_of(lines, index),
                }
            )
        index += 1
    return {"name": name, "items": items} if name else None


def _fenced(lines: list[str], start: int) -> tuple[str, int]:
    """The body of a ``` block, dedented, and the line it ends on."""
    collected: list[str] = []
    index = start + 1
    while index < len(lines) and lines[index].strip() != "```":
        collected.append(lines[index].strip())
        index += 1
    return "\n".join(collected), index


def _datatype_of(lines: list[str], start: int) -> str:
    """The `dataType:` belonging to the item starting at `start`.

    Stops at the next item rather than scanning the file, so a column with no
    declared type does not inherit the next one's.
    """
    for line in lines[start + 1 : start + 8]:
        if _ITEM.match(line) or _TABLE.match(line):
            break
        found = _DATATYPE.match(line)
        if found:
            return found.group(1).lower()
    return ""


def _parse_relationships(body: str) -> list[dict]:
    found: list[dict] = []
    current: dict | None = None
    for line in body.splitlines():
        if _RELATIONSHIP.match(line):
            current = {"kind": "many_to_one"}
            found.append(current)
            continue
        if current is None:
            continue
        column = _REL_COLUMN.match(line)
        if column:
            side = column.group(1)
            current[f"{side}_table"] = _unquote(column.group(2), column.group(3))
            current[f"{side}_column"] = _unquote(column.group(4), column.group(5))
            continue
        cross = _CROSS_FILTER.match(line)
        if cross and cross.group(1) == "bothDirections":
            current["kind"] = "many_to_many"
    return [row for row in found if "from_table" in row and "to_table" in row]


# --- PBIR --------------------------------------------------------------------


def _parse_pages(files: Mapping[str, str]) -> list[dict]:
    pages: list[dict] = []
    for path, text in sorted(files.items()):
        if not path.endswith("/page.json"):
            continue
        try:
            page = json.loads(text)
        except json.JSONDecodeError:
            continue
        page_id = page.get("name") or path
        prefix = path.rsplit("/", 1)[0] + "/visuals/"
        visuals = [
            visual
            for visual_path, visual_text in sorted(files.items())
            if visual_path.startswith(prefix) and visual_path.endswith("/visual.json")
            for visual in (_parse_visual(visual_text, page.get("displayName", page_id)),)
            if visual is not None
        ]
        pages.append(
            {"id": page_id, "name": page.get("displayName", page_id), "visuals": visuals}
        )
    return pages


def _parse_visual(text: str, page_name: str) -> Visual | None:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None
    body = raw.get("visual") or {}
    wells = ((body.get("query") or {}).get("queryState") or {})

    bindings: list[VisualBinding] = []
    for well, content in wells.items():
        role = _ROLES.get(well.lower(), BindingRole.DETAIL)
        for projection in content.get("projections") or []:
            binding = _binding(projection.get("field"), role)
            if binding is not None:
                bindings.append(binding)

    filters = [
        binding
        for entry in ((raw.get("filterConfig") or {}).get("filters") or [])
        for binding in (_binding(entry.get("field"), BindingRole.FILTER),)
        if binding is not None
    ]

    return Visual(
        id=raw.get("name", page_name),
        name=_title(body) or page_name,
        visual_type=body.get("visualType", "unknown"),
        bindings=bindings,
        filters=filters,
    )


def _binding(field_spec: dict | None, role: BindingRole) -> VisualBinding | None:
    """A PBIR projection becomes a binding.

    A projection names either a `Column` or a `Measure`; both are a field in a
    well, and the canonical model does not distinguish them here because the
    grain already lives on the column.
    """
    if not isinstance(field_spec, dict):
        return None
    # A Sum of a column is written as an Aggregation around the Column.
    aggregated = field_spec.get("Aggregation")
    if isinstance(aggregated, dict) and isinstance(aggregated.get("Expression"), dict):
        field_spec = aggregated["Expression"]
    for key in ("Column", "Measure"):
        spec = field_spec.get(key)
        if not isinstance(spec, dict):
            continue
        entity = (
            ((spec.get("Expression") or {}).get("SourceRef") or {}).get("Entity") or ""
        )
        prop = spec.get("Property") or ""
        if not prop:
            continue
        return VisualBinding(
            role=role,
            field=FieldRef(table=entity, column=prop),
            resolvable=True,
            raw=f"{entity}.{prop}" if entity else prop,
        )
    return None


def _title(body: dict) -> str:
    """The visual's title, when it was set to a literal.

    A title bound to an expression is left alone: rendering the expression as
    if it were the title would put a formula where a reader expects words.
    """
    entries = ((body.get("objects") or {}).get("title") or [])
    for entry in entries:
        literal = (
            (((entry.get("properties") or {}).get("text") or {}).get("expr") or {})
            .get("Literal", {})
            .get("Value")
        )
        if isinstance(literal, str):
            return literal.strip("'")
    return ""


# --- to the canonical model ---------------------------------------------------


def _column(table_name: str, item: dict) -> Column:
    """One TMDL item as a canonical column.

    A `measure` evaluates over a set of rows and a `column =` evaluates within
    one, which is precisely the grain distinction - so it is read off the
    keyword rather than inferred from the expression.
    """
    expression = (
        Expression(source_language="dax", source_text=item["expression"])
        if item["expression"]
        else None
    )
    return Column(
        id=f"{table_name}.{item['name']}",
        name=item["name"],
        datatype=_DATATYPES.get(item["datatype"], DataType.UNKNOWN),
        grain=(
            Grain.AGGREGATE
            if item["kind"] == "measure"
            else (Grain.ROW if expression else None)
        ),
        expression=expression,
        # Never set. Nothing here has understood the expression; `P6a.2` is
        # where that starts, and a translation written now would be an
        # equivalence nobody computed.
        translation=None,
    )


def _relationship(row: dict) -> Relationship:
    return Relationship(
        from_table=row["from_table"],
        from_column=row["from_column"],
        to_table=row["to_table"],
        to_column=row["to_column"],
        kind=row["kind"],
    )


def _model_name(files: Mapping[str, str], fallback: str) -> str:
    for path in files:
        if path.endswith(".pbip"):
            return path.rsplit("/", 1)[-1][: -len(".pbip")]
    return fallback
