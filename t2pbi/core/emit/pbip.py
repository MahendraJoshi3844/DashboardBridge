"""Write the PBIP project folder (deterministically) from the IR."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from t2pbi.core.emit.params import param_table_tmdl
from t2pbi.core.emit.paths import safe_path_name
from t2pbi.core.emit.pbir import DEFINITION_VERSION, write_report_definition
from t2pbi.core.emit.tmdl import (
    emitted_columns,
    model_tmdl,
    relationships_tmdl,
    table_tmdl,
)
from t2pbi.core.mapping import FieldRef, PBIFilter, PBIVisual, map_visuals
from t2pbi.ir import Relationship, Severity, Workbook


def _resolve_relationship_columns(wb: Workbook) -> list[Relationship]:
    """Rewrite relationship column refs to the column's emitted display name."""
    display: dict[tuple[str, str], str] = {}
    for table in wb.all_tables():
        for col in table.columns:
            display[(table.name, col.name)] = col.display_name
    resolved: list[Relationship] = []
    for r in wb.relationships:
        resolved.append(
            Relationship(
                from_table=r.from_table,
                from_column=display.get((r.from_table, r.from_column), r.from_column),
                to_table=r.to_table,
                to_column=display.get((r.to_table, r.to_column), r.to_column),
                kind=r.kind,
            )
        )
    return resolved


def _bind_to_emitted(wb: Workbook, visuals: list[PBIVisual]) -> list[PBIVisual]:
    """Drop every field binding that points at a column this model does not have.

    The mapper binds a shelf field to any column it can find in the IR, and it
    has to: mapping runs before translation, so at that point every calculation
    still looks as though it will convert. The ones that are then refused are
    never written to TMDL, and the binding made for them becomes a reference to
    a column that does not exist. Power BI opens such a report and shows the
    visual broken, which is the guessed visual this project refuses to emit -
    it is simply guessed by omission rather than on purpose.

    So the last stage, which is the only one that knows what was really
    written, prunes them and reports each one. The name is normalised at the
    same time: a shelf may name a column by its internal name while the model
    carries its caption, and pointing at the wrong one of those two dangles
    just as badly.
    """
    emitted: dict[str, dict[str, str]] = {
        table.name: emitted_columns(table) for table in wb.all_tables()
    }
    # A what-if parameter table carries one column, named for the parameter.
    for param in wb.parameters:
        emitted[param.display_name] = {param.display_name: param.display_name}

    # What a person calls the field, for every column the workbook has - not
    # only the ones that were written. A refused calculation is exactly the
    # case this reports, and its internal name ("Calculation_4120925132203686")
    # appears nowhere in the reader's Tableau; its caption ("Rank over 3") is
    # the only name they can act on.
    spoken: dict[tuple[str, str], str] = {
        (table.name, col.name): col.display_name
        for table in wb.all_tables()
        for col in table.columns
    }

    def keep(sheet: str, refs: list[FieldRef]) -> list[FieldRef]:
        bound: list[FieldRef] = []
        for ref in refs:
            written = emitted.get(ref.table, {}).get(ref.column)
            if written is None:
                # Falls back to the shelf's own word: a field the workbook has
                # never heard of has no caption to substitute, and inventing a
                # friendlier name for it would be a guess.
                named = spoken.get((ref.table, ref.column), ref.column)
                wb.add_flag(
                    item=f"{sheet}: {named}",
                    severity=Severity.MANUAL,
                    reason=(
                        f"'{named}' is not in the produced model, most often "
                        "because its calculation was not translated, so the field "
                        "well was left empty rather than pointed at a column that "
                        "is not there. Add it by hand once the calculation exists."
                    ),
                    stage="emit",
                )
                continue
            bound.append(FieldRef(table=ref.table, column=written))
        return bound

    def keep_filters(sheet: str, filters: list[PBIFilter]) -> list[PBIFilter]:
        """The same pruning and the same renaming, for page filters.

        A filter carries a column reference exactly as a field well does, and it
        dangles exactly as badly - except that a filter naming a column the
        model does not have does not merely draw an empty visual, it is a page
        Power BI cannot resolve at all.

        The rename matters more here than the drop. `map_visuals` knows the
        shelf's word for the field, which may be the internal name, while TMDL
        writes the caption; only this stage knows which one is in the file.
        The drop is a backstop: `_carry_over` already refuses a calculated field
        whose DAX was refused, so it should never fire - and "should never" is
        the reason it reports rather than passes quietly.
        """
        kept: list[PBIFilter] = []
        for filter_ in filters:
            written = emitted.get(filter_.field.table, {}).get(filter_.field.column)
            if written is None:
                named = spoken.get(
                    (filter_.field.table, filter_.field.column), filter_.field.column
                )
                wb.add_flag(
                    item=f"{sheet}: {named}",
                    severity=Severity.MANUAL,
                    reason=(
                        f"The filter on '{named}' was not written, because that "
                        "column is not in the produced model. Recreate the filter "
                        "by hand once the column exists."
                    ),
                    stage="emit",
                )
                continue
            kept.append(
                PBIFilter(
                    field=FieldRef(table=filter_.field.table, column=written),
                    values=filter_.values,
                    excludes=filter_.excludes,
                )
            )
        return kept

    return [
        PBIVisual(
            name=visual.name,
            visual_type=visual.visual_type,
            category=keep(visual.name, visual.category),
            values=keep(visual.name, visual.values),
            legend=keep(visual.name, visual.legend),
            filters=keep_filters(visual.name, visual.filters),
        )
        for visual in visuals
    ]


def _stable_guid(seed: str) -> str:
    """Deterministic GUID-shaped id from a name (never random)."""
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _clear_generated(directory: Path) -> None:
    """Remove a wholly generated folder so a re-run cannot inherit stale items.

    Only the per-item folders this emitter owns (tables, pages) are cleared;
    anything Power BI Desktop writes alongside them is left in place.
    """
    if not directory.is_dir():
        return
    for child in sorted(directory.iterdir()):
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def write_pbip(
    wb: Workbook,
    out_dir: str | Path,
    project_name: str,
    visuals: list[PBIVisual] | None = None,
) -> Path:
    out = Path(out_dir)
    # Every component below is a name from a workbook or from whoever named
    # the project, so none of them is allowed to be a path (see emit/paths).
    name = safe_path_name(project_name, fallback="Project")
    model_dir = out / f"{name}.SemanticModel"
    report_dir = out / f"{name}.Report"

    # A previous conversion into this folder leaves per-item files behind, and
    # Power BI would load them as part of this model.
    _clear_generated(model_dir / "definition" / "tables")
    _clear_generated(report_dir / "definition" / "pages")

    tables = wb.all_tables()
    param_names = [p.display_name for p in wb.parameters]
    table_names = [t.name for t in tables] + param_names

    # --- Semantic model ---
    model_content = model_tmdl(table_names)
    rels = relationships_tmdl(_resolve_relationship_columns(wb))
    if rels:
        model_content = model_content.rstrip() + "\n\n" + rels
    _write(model_dir / "definition" / "model.tmdl", model_content)
    for ds in wb.datasources:
        for table in ds.tables:
            _write(
                model_dir / "definition" / "tables" / f"{safe_path_name(table.name)}.tmdl",
                table_tmdl(table, workbook=wb, datasource=ds.name),
            )
    # What-if parameter tables (one file each).
    for param in wb.parameters:
        _write(
            model_dir
            / "definition"
            / "tables"
            / f"{safe_path_name(param.display_name)}.tmdl",
            param_table_tmdl(param, workbook=wb),
        )
    _write(
        model_dir / "definition.pbism",
        json.dumps({"version": DEFINITION_VERSION, "settings": {}}, indent=2) + "\n",
    )
    _write(
        model_dir / ".platform",
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
                "metadata": {"type": "SemanticModel", "displayName": name},
                "config": {"version": "2.0", "logicalId": _stable_guid(name + ".model")},
            },
            indent=2,
        )
        + "\n",
    )

    # --- Report: PBIR definition (pages + visuals mapped from worksheets) ---
    if visuals is None:
        visuals = map_visuals(wb)
    write_report_definition(_bind_to_emitted(wb, visuals), report_dir)
    _write(
        report_dir / "definition.pbir",
        json.dumps(
            {
                "version": DEFINITION_VERSION,
                "datasetReference": {
                    "byPath": {"path": f"../{name}.SemanticModel"}
                },
            },
            indent=2,
        )
        + "\n",
    )
    _write(
        report_dir / ".platform",
        json.dumps(
            {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
                "metadata": {"type": "Report", "displayName": name},
                "config": {"version": "2.0", "logicalId": _stable_guid(name + ".report")},
            },
            indent=2,
        )
        + "\n",
    )

    # --- .pbip pointer ---
    _write(
        out / f"{name}.pbip",
        json.dumps(
            {
                "version": "1.0",
                "artifacts": [{"report": {"path": f"{name}.Report"}}],
                "settings": {"enableAutoRecovery": True},
            },
            indent=2,
        )
        + "\n",
    )

    return out / f"{name}.pbip"
