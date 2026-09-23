# Module Spec — IR (Intermediate Representation)

**Code:** `engines/t2pbi/ir/model.py`

## Purpose
The single, technology-neutral data model that decouples "read Tableau" from "write
Power BI". Every pipeline stage reads/writes only the IR.

## Types
- `Severity` — `INFO | WARNING | MANUAL` (manual = needs a human).
- `ConversionFlag(item, severity, reason, stage)` — one record of anything not
  converted cleanly. Feeds the Migration Report. **Nothing is dropped silently.**
- `Column(name, datatype, role, caption=None, formula=None, dax=None)` —
  role ∈ {`dimension`, `measure`}; `formula` = original Tableau calc; `dax` = the
  translation (or None if unsupported).
- `Relationship(from_table, from_column, to_table, to_column, kind="many_to_one")`.
- `Table(name, columns[], relationships[])`.
- `DataSource(name, connection, tables[], is_extract)`.
- `Encoding(rows[], cols[], color=None, size=None, label=None, detail=None)`.
- `Worksheet(name, visual_type, encoding, filters[])`.
- `Dashboard(name, sheet_names[])`.
- `Workbook(version, datasources[], worksheets[], dashboards[], flags[])`.

## Behaviour
- Pure dataclasses, no I/O, no logic beyond simple helpers (`add_flag`, `all_tables`).
- Deterministic: no sets used where order matters in output.

## Acceptance
- Importable; instances round-trip via `dataclasses.asdict`; `add_flag` appends.
