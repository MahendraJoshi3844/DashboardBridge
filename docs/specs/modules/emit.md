# Module Spec — Emit (TMDL / PBIP)

**Code:** `engines/t2pbi/core/emit/` (`datatypes.py`, `tmdl.py`, `pbip.py`)

## Purpose
Stage 5. Turn the `Workbook` IR into a PBIP project on disk: a text-based TMDL
semantic model plus the `.pbip` scaffold and a minimal report.

## Inputs
- `Workbook` IR, `out_dir: Path`, `project_name: str`.

## Outputs (folder)
```
<out>/<name>.pbip
<out>/<name>.SemanticModel/.platform
<out>/<name>.SemanticModel/definition.pbism
<out>/<name>.SemanticModel/definition/model.tmdl
<out>/<name>.SemanticModel/definition/tables/<Table>.tmdl
<out>/<name>.Report/.platform
<out>/<name>.Report/definition.pbir
```

## Behaviour
- **datatypes.py:** map Tableau datatype → TMDL dataType
  (`integer→int64`, `real→double`, `string→string`, `boolean→boolean`,
  `date/datetime→dateTime`; unknown→`string` + WARNING flag).
- **tmdl.py:** one `<Table>.tmdl` per table: each non-calculated column as a `column`;
  each calculated column **with successful DAX** as a `measure`; calculated columns
  without DAX are skipped here (already flagged MANUAL by the translate step).
- **pbip.py:** write the `.pbip`, `.platform`, `definition.pbism`, `definition.pbir`,
  and `model.tmdl` (model header + table refs). Deterministic: stable ordering;
  any GUID derived from a name via a stable hash, never random.

## Edge cases
| Case | Handling |
|---|---|
| Illegal TMDL name (quotes/newlines) | sanitize + record rename flag |
| Table with zero columns | still emit the table stub |
| Out dir exists & non-empty | caller decides; emit writes into a clean subfolder |

## Scope note (v1.1)
Visual→PBIR field-well emission is now implemented in `emit/pbir.py` (driven by
`core/mapping/visual_map.py`) — see [visual.md](visual.md). The emitter writes the
semantic model plus a real PBIR report (pages + visuals). Exact PBIR schema fidelity
is confirmed by opening the project in Power BI Desktop.

## Acceptance
- Generates the folder structure above deterministically (golden snapshot).
- Measures appear only for calculated columns that produced valid DAX.
