"""What is actually on disk, read back as data.

Validation compares the canonical source model against the *artifact*, not
against the emitter's intentions. So this module re-reads the produced PBIP —
TMDL and PBIR — with its own parser and shares no code with the writer. A check
that asks the emitter what it emitted proves only that the emitter is
self-consistent.

The parser is deliberately shallow. It answers exactly the questions
08-validation-engine asks (what tables, columns, measures, partitions,
relationships, pages, visuals and field bindings exist) and nothing else. A
fuller TMDL parser would be a second source of truth for a format we do not
own.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

# `\tcolumn 'Name'` or `\tcolumn 'Name' = <expression>`. The emitter writes one
# expression per line; a continuation line is indented deeper and is ignored
# here because no check depends on it.
_ITEM = re.compile(r"^\t(column|measure|partition|hierarchy)\s+'([^']*)'(?:\s*=\s*(.*))?$")
_TABLE = re.compile(r"^table\s+'([^']*)'\s*$")
_REF_TABLE = re.compile(r"^ref\s+table\s+'([^']*)'\s*$")
_REL = re.compile(r"^relationship\s+(\S+)\s*$")
_REL_COLUMN = re.compile(r"^\t(from|to)Column:\s*'([^']*)'\.'([^']*)'\s*$")

#: `'Table'[Column]` — a fully qualified reference in emitted DAX.
QUALIFIED_REF = re.compile(r"'([^']+)'\[([^\]]+)\]")
#: `[Measure]` not preceded by a table qualifier.
BARE_REF = re.compile(r"(?<!\])(?<!')\[([^\]]+)\]")


@dataclass(frozen=True)
class TargetTable:
    name: str
    columns: tuple[str, ...] = ()
    calculated_columns: tuple[tuple[str, str], ...] = ()
    measures: tuple[tuple[str, str], ...] = ()
    partitions: tuple[str, ...] = ()

    @property
    def has_partition(self) -> bool:
        return bool(self.partitions)

    def names(self) -> set[str]:
        return (
            set(self.columns)
            | {name for name, _ in self.calculated_columns}
            | {name for name, _ in self.measures}
        )


@dataclass(frozen=True)
class TargetRelationship:
    from_table: str
    from_column: str
    to_table: str
    to_column: str


@dataclass(frozen=True)
class TargetBinding:
    """One field projected into one well of an emitted visual."""

    well: str
    table: str
    column: str


@dataclass(frozen=True)
class TargetVisual:
    visual_type: str
    bindings: tuple[TargetBinding, ...] = ()


@dataclass(frozen=True)
class TargetPage:
    page_id: str
    display_name: str
    visuals: tuple[TargetVisual, ...] = ()


@dataclass(frozen=True)
class SemanticModel:
    tables: tuple[TargetTable, ...] = ()
    referenced_tables: tuple[str, ...] = ()
    relationships: tuple[TargetRelationship, ...] = ()
    present: bool = False

    def table(self, name: str) -> TargetTable | None:
        for table in self.tables:
            if table.name == name:
                return table
        return None


@dataclass(frozen=True)
class Report:
    pages: tuple[TargetPage, ...] = ()
    page_order: tuple[str, ...] = ()
    definition_present: bool = False

    def page_titled(self, title: str) -> TargetPage | None:
        for page in self.pages:
            if page.display_name == title:
                return page
        return None


@dataclass(frozen=True)
class TargetProject:
    """Every file the conversion wrote, addressed by POSIX-relative path.

    Held as bytes rather than text because the determinism check hashes what was
    written, and a decode-then-compare would hide a difference in encoding.
    """

    files: Mapping[str, bytes] = field(default_factory=dict)

    # -- construction -------------------------------------------------------

    @classmethod
    def from_dir(cls, root: str | Path) -> TargetProject:
        base = Path(root)
        return cls(
            files={
                path.relative_to(base).as_posix(): path.read_bytes()
                for path in sorted(base.rglob("*"))
                if path.is_file()
            }
        )

    @classmethod
    def from_zip(cls, data: bytes) -> TargetProject:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return cls(
                files={
                    info.filename: archive.read(info)
                    for info in sorted(archive.infolist(), key=lambda i: i.filename)
                    if not info.is_dir()
                }
            )

    # -- raw access ---------------------------------------------------------

    def digests(self) -> dict[str, str]:
        return {
            path: hashlib.sha256(data).hexdigest()
            for path, data in sorted(self.files.items())
        }

    def text(self, path: str) -> str | None:
        data = self.files.get(path)
        if data is None:
            return None
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None

    def paths(self, *, suffix: str = "", contains: str = "") -> list[str]:
        return sorted(
            path
            for path in self.files
            if path.endswith(suffix) and contains in path
        )

    # -- parsed views -------------------------------------------------------

    def semantic_model(self) -> SemanticModel:
        model_paths = self.paths(suffix="definition/model.tmdl")
        tables = tuple(
            _parse_table(self.text(path) or "")
            for path in self.paths(suffix=".tmdl")
            if "/definition/tables/" in path
        )
        tables = tuple(t for t in tables if t is not None)
        refs: tuple[str, ...] = ()
        relationships: tuple[TargetRelationship, ...] = ()
        if model_paths:
            body = self.text(model_paths[0]) or ""
            refs = tuple(_REF_TABLE.match(line).group(1) for line in body.splitlines() if _REF_TABLE.match(line))
            relationships = _parse_relationships(body)
        return SemanticModel(
            tables=tuple(sorted(tables, key=lambda t: t.name)),
            referenced_tables=refs,
            relationships=relationships,
            present=bool(model_paths),
        )

    def report(self) -> Report:
        pages: list[TargetPage] = []
        for path in self.paths(suffix="/page.json"):
            raw = self.text(path)
            if raw is None:
                continue
            try:
                page = json.loads(raw)
            except json.JSONDecodeError:
                continue
            page_dir = path.rsplit("/page.json", 1)[0]
            visuals = tuple(
                visual
                for visual_path in self.paths(suffix="/visual.json", contains=page_dir + "/visuals/")
                if (visual := _parse_visual(self.text(visual_path))) is not None
            )
            pages.append(
                TargetPage(
                    page_id=str(page.get("name", "")),
                    display_name=str(page.get("displayName", "")),
                    visuals=visuals,
                )
            )
        order: tuple[str, ...] = ()
        index = self.paths(suffix="pages/pages.json")
        if index:
            try:
                order = tuple(json.loads(self.text(index[0]) or "{}").get("pageOrder", []))
            except json.JSONDecodeError:
                order = ()
        return Report(
            pages=tuple(sorted(pages, key=lambda p: (p.display_name, p.page_id))),
            page_order=order,
            definition_present=bool(self.paths(suffix="definition.pbir")),
        )

    def pbip_manifest_present(self) -> bool:
        return bool(self.paths(suffix=".pbip"))


# ---------------------------------------------------------------------------
# TMDL
# ---------------------------------------------------------------------------


def _parse_table(body: str) -> TargetTable | None:
    lines = body.splitlines()
    name = ""
    for line in lines:
        match = _TABLE.match(line)
        if match:
            name = match.group(1)
            break
    if not name:
        return None

    columns: list[str] = []
    calculated: list[tuple[str, str]] = []
    measures: list[tuple[str, str]] = []
    partitions: list[str] = []
    for line in lines:
        match = _ITEM.match(line)
        if not match:
            continue
        kind, item, expression = match.group(1), match.group(2), match.group(3)
        if kind == "column":
            (calculated.append((item, expression)) if expression else columns.append(item))
        elif kind == "measure":
            measures.append((item, expression or ""))
        elif kind == "partition":
            partitions.append(item)
    return TargetTable(
        name=name,
        columns=tuple(columns),
        calculated_columns=tuple(calculated),
        measures=tuple(measures),
        partitions=tuple(partitions),
    )


def _parse_relationships(body: str) -> tuple[TargetRelationship, ...]:
    found: list[TargetRelationship] = []
    current: dict[str, tuple[str, str]] = {}
    for line in body.splitlines():
        if _REL.match(line):
            current = {}
            continue
        match = _REL_COLUMN.match(line)
        if not match:
            continue
        current[match.group(1)] = (match.group(2), match.group(3))
        if "from" in current and "to" in current:
            found.append(
                TargetRelationship(
                    from_table=current["from"][0],
                    from_column=current["from"][1],
                    to_table=current["to"][0],
                    to_column=current["to"][1],
                )
            )
            current = {}
    return tuple(found)


# ---------------------------------------------------------------------------
# PBIR
# ---------------------------------------------------------------------------


def _parse_visual(raw: str | None) -> TargetVisual | None:
    if raw is None:
        return None
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        return None
    visual = document.get("visual")
    if not isinstance(visual, dict):
        return None
    bindings: list[TargetBinding] = []
    state = visual.get("query", {}).get("queryState", {})
    for well in sorted(state) if isinstance(state, dict) else []:
        for projection in state[well].get("projections", []):
            column = projection.get("field", {}).get("Column", {})
            entity = (
                column.get("Expression", {}).get("SourceRef", {}).get("Entity", "")
            )
            bindings.append(
                TargetBinding(
                    well=well, table=str(entity), column=str(column.get("Property", ""))
                )
            )
    return TargetVisual(
        visual_type=str(visual.get("visualType", "")), bindings=tuple(bindings)
    )
