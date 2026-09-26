# Module Spec — Parse

**Code:** `t2pbi/core/parse/` (`datasources.py`, `worksheets.py`, `dashboards.py`,
`__init__.py:parse_workbook`)

## Purpose
Stage 2. Turn raw `.twb` XML bytes into a populated `Workbook` IR.

## Inputs
- `twb_bytes: bytes` (from Extract).

## Outputs
- `Workbook` IR (datasources, worksheets, dashboards, version) + flags for anything
  ambiguous.

## Behaviour
- Parse with `lxml.etree` (XML from bytes). Use targeted element iteration; clear
  large subtrees to bound memory.
- **Datasources:** for each `<datasource>` (skip the internal `Parameters` one),
  read `<column>` elements → `Column(name, datatype, role, caption, formula)`.
  A `<calculation class="tableau" formula=...>` child marks a calculated field.
  Map columns under their source `<relation>`/table; if no clear table, group under a
  single table named after the datasource.
- **Worksheets:** normalize the mark `class` (`Bar`→bar, `Line`→line, `Area`→area,
  `Square`/`Text`→table, `Circle`/`Shape`→scatter, `Pie`→pie, else unknown) into
  `visual_type`; capture `<rows>`/`<cols>` field references into the `Encoding`.
- **Dashboards:** name + the worksheet names referenced inside.

## Edge cases
| Case | Handling |
|---|---|
| Field name like `[Calculation_123]` with caption | keep caption as display name |
| Datatype missing | default to `"string"` + WARNING flag |
| Parameters datasource | skip (not a model table) |
| Worksheet with no recognizable mark | `visual_type="unknown"` + WARNING flag |

## Acceptance
- A real `.twb` parses into a Workbook with ≥1 datasource, columns with correct roles,
  calculated fields carrying their `formula`, and worksheets with a `visual_type`.
- Pure read: never writes output; deterministic ordering preserved from document order.
