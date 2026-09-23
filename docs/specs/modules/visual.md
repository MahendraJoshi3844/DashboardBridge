# Module Spec — Visual mapping + PBIR emit (v1.1)

**Code:** `engines/t2pbi/core/mapping/visual_map.py`, `engines/t2pbi/core/emit/pbir.py`

## Purpose
Recreate the v1 basic visuals: map each Tableau worksheet to a Power BI visual
(type + field wells), and emit them into the PBIR report (pages + visuals).

## Inputs
- `Workbook` IR (worksheets + tables for field→table resolution).

## Outputs
- `list[PBIVisual]` from the mapping step.
- PBIR files under `<name>.Report/definition/`:
  `report.json`, `pages/pages.json`, `pages/<page>/page.json`,
  `pages/<page>/visuals/<v>/visual.json`. One page per worksheet, one visual per page.

## Mapping rules
| Tableau visual_type | Power BI visualType |
|---|---|
| bar | clusteredBarChart |
| line | lineChart |
| area | areaChart |
| pie | pieChart |
| scatter | scatterChart |
| table | tableEx |
| kpi | card |
| unknown | tableEx (+ WARNING flag) |

Field wells (v1): `category` ← encoding.cols, `values` ← encoding.rows,
`legend` ← encoding.color. A field name is resolved to its table via a field→table
index; unresolved fields fall back to the first table + a WARNING flag.

## Determinism & honesty
- Stable ordering; deterministic visual/page names and positions (grid layout).
- Each generated visual raises an INFO flag "visual generated — verify layout in
  Power BI", because exact PBIR fidelity is only confirmable by opening in Power BI
  Desktop. We never claim pixel-perfect; we recover structure + field wells.

## Edge cases
| Case | Handling |
|---|---|
| Worksheet with no fields | emit an empty visual of the mapped type + INFO flag |
| Field not found in any table | use first table + WARNING flag (never crash) |
| No worksheets | emit a single empty page (valid report) |

## Acceptance
- `map_visuals` returns correct types + field wells for the sample (unit-tested).
- PBIR files generated deterministically (snapshot/structure test).
- Field→table resolution flags unresolved fields rather than guessing silently.
