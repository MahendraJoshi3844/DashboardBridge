"""The produced Power BI project, read and edited as text.

The workspace shows a person the model the converter wrote and lets them change
two things by hand: a measure's DAX and a table's Power Query. Both live in the
table's `.tmdl` file, so an edit is a text edit of that file, and a save is a
new archive with that file replaced. Nothing is regenerated from the canonical
model: the person is editing the output, and re-running the converter would
discard what they wrote.

## What this reads

TMDL as `engines/t2pbi/core/emit/tmdl.py` writes it, plus the multi-line form
Power BI Desktop uses (a triple-backtick block for a measure, an indented block
for a partition source), because a saved edit may introduce one. It is a reader
for this project's output, not a general TMDL parser, and says so by refusing
what it cannot find rather than guessing where to write.

## What an edit is not

Not a translation, and never marked as one. A measure written here is a
person's DAX; the conversion report still says what the converter did.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

from dashboardbridge_contracts import (
    WorkspaceColumn,
    WorkspaceEdit,
    WorkspaceFile,
    WorkspaceMeasure,
    WorkspacePartition,
    WorkspaceTable,
)

_TABLE = re.compile(r"^table\s+(?:'((?:[^']|'')*)'|(\S+))\s*$")
_COLUMN = re.compile(r"^\tcolumn\s+(?:'((?:[^']|'')*)'|([^\s=]+))")
_MEASURE = re.compile(r"^\tmeasure\s+(?:'((?:[^']|'')*)'|([^\s=]+))\s*=\s?(.*)$")
_PARTITION = re.compile(r"^\tpartition\s+(?:'((?:[^']|'')*)'|([^\s=]+))\s*=\s*(\w*)")
_PROPERTY = re.compile(r"^\t\t(\w+):\s*(.*)$")
_SOURCE = re.compile(r"^\t\tsource\s*=\s?(.*)$")
_FENCE = "```"


class EditRefused(ValueError):
    """An edit that names something the project does not hold."""


def _name(match: re.Match[str]) -> str:
    quoted, bare = match.group(1), match.group(2)
    return quoted.replace("''", "'") if quoted is not None else bare


def _quote(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {
            name: archive.read(name)
            for name in sorted(archive.namelist())
            if not name.endswith("/")
        }


def rezip(files: dict[str, bytes]) -> bytes:
    """Deterministic: fixed order and a fixed timestamp, so a save diffs cleanly."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[name])
    return buffer.getvalue()


def file_list(files: dict[str, bytes]) -> list[WorkspaceFile]:
    return [WorkspaceFile(path=path, size_bytes=len(body)) for path, body in sorted(files.items())]


def _table_files(files: dict[str, bytes]) -> dict[str, str]:
    """Table name to the path of its `.tmdl`, read off the file's first line."""
    found: dict[str, str] = {}
    for path, body in files.items():
        if "/definition/tables/" not in path or not path.endswith(".tmdl"):
            continue
        for line in body.decode("utf-8", errors="replace").splitlines():
            match = _TABLE.match(line)
            if match:
                found[_name(match)] = path
                break
    return found


@dataclass
class _Block:
    """A multi-line value: where it starts, where it ends, and its text."""

    start: int
    end: int  # exclusive
    text: str


def _measure_block(lines: list[str], index: int, first: str) -> _Block:
    if first.strip() == _FENCE:
        body: list[str] = []
        cursor = index + 1
        while cursor < len(lines) and lines[cursor].strip() != _FENCE:
            body.append(lines[cursor].strip("\t"))
            cursor += 1
        return _Block(index, min(cursor + 1, len(lines)), "\n".join(body))
    return _Block(index, index + 1, first.strip())


def _source_block(lines: list[str], index: int, first: str) -> _Block:
    if first.strip():
        return _Block(index, index + 1, first.strip())
    body: list[str] = []
    cursor = index + 1
    while cursor < len(lines) and lines[cursor].startswith("\t\t\t"):
        body.append(lines[cursor][3:].lstrip("\t"))
        cursor += 1
    return _Block(index, cursor, "\n".join(body))


def read_tables(files: dict[str, bytes]) -> list[WorkspaceTable]:
    tables: list[WorkspaceTable] = []
    for name, path in sorted(_table_files(files).items()):
        lines = files[path].decode("utf-8", errors="replace").splitlines()
        columns: list[WorkspaceColumn] = []
        measures: list[WorkspaceMeasure] = []
        partitions: list[WorkspacePartition] = []
        current: WorkspaceColumn | None = None
        partition: dict | None = None
        for index, line in enumerate(lines):
            if match := _COLUMN.match(line):
                current = WorkspaceColumn(name=_name(match))
                columns.append(current)
                partition = None
            elif match := _MEASURE.match(line):
                block = _measure_block(lines, index, match.group(3))
                measures.append(WorkspaceMeasure(name=_name(match), expression=block.text))
                current = partition = None
            elif match := _PARTITION.match(line):
                partition = {
                    "name": _name(match),
                    "mode": "",
                    "source_kind": match.group(3) or "m",
                    "expression": "",
                }
                partitions.append(partition)  # type: ignore[arg-type]
                current = None
            elif partition is not None and (source := _SOURCE.match(line)):
                partition["expression"] = _source_block(lines, index, source.group(1)).text
            elif (prop := _PROPERTY.match(line)) is not None:
                key, value = prop.group(1), prop.group(2).strip()
                if current is not None and key == "dataType":
                    columns[-1] = current = current.model_copy(update={"data_type": value})
                elif partition is not None and key == "mode":
                    partition["mode"] = value
        tables.append(
            WorkspaceTable(
                name=name,
                columns=columns,
                measures=measures,
                partitions=[WorkspacePartition(**item) for item in partitions],  # type: ignore[arg-type]
            )
        )
    return tables


def _measure_lines(name: str, expression: str) -> list[str]:
    text = expression.strip()
    if "\n" not in text:
        return [f"\tmeasure {_quote(name)} = {text}"]
    return [
        f"\tmeasure {_quote(name)} = {_FENCE}",
        *[f"\t\t\t{line}" for line in text.splitlines()],
        f"\t\t\t{_FENCE}",
    ]


def _source_lines(expression: str) -> list[str]:
    text = expression.strip()
    if "\n" not in text:
        return [f"\t\tsource = {text}"]
    return ["\t\tsource =", *[f"\t\t\t\t{line}" for line in text.splitlines()]]


def _apply_one(text: str, edit: WorkspaceEdit) -> str:
    lines = text.splitlines()
    if edit.kind == "measure":
        for index, line in enumerate(lines):
            match = _MEASURE.match(line)
            if match and _name(match) == edit.name:
                block = _measure_block(lines, index, match.group(3))
                lines[block.start : block.end] = _measure_lines(edit.name, edit.expression)
                return "\n".join(lines) + "\n"
        # A new measure, which is how a held calculation gets written by hand.
        # Placed before the first partition, where the emitter puts measures.
        at = next(
            (index for index, line in enumerate(lines) if _PARTITION.match(line)),
            len(lines),
        )
        lines[at:at] = [*_measure_lines(edit.name, edit.expression), ""]
        return "\n".join(lines) + "\n"

    inside = False
    for index, line in enumerate(lines):
        match = _PARTITION.match(line)
        if match:
            inside = _name(match) == edit.name
            continue
        if inside and (source := _SOURCE.match(line)):
            block = _source_block(lines, index, source.group(1))
            lines[block.start : block.end] = _source_lines(edit.expression)
            return "\n".join(lines) + "\n"
        if inside and line and not line.startswith("\t\t"):
            inside = False
    raise EditRefused(
        f"Table {edit.table} has no partition called {edit.name}, so there is "
        "no Power Query to change."
    )


def apply_edits(files: dict[str, bytes], edits: list[WorkspaceEdit]) -> dict[str, bytes]:
    """Every edit, or none: a refusal leaves the project exactly as it was."""
    paths = _table_files(files)
    changed = dict(files)
    for edit in edits:
        path = paths.get(edit.table)
        if path is None:
            raise EditRefused(f"This project has no table called {edit.table}.")
        text = changed[path].decode("utf-8")
        changed[path] = _apply_one(text, edit).encode("utf-8")
    return changed
