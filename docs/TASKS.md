# Task Breakdown — v1 (derived from the Technical Design)

> SDD step 5: concrete tasks extracted from the Technical Design Plan.
> Each task is small enough to be one focused Claude Code session on its own branch.
> Order respects dependencies. Check off as completed.

## Milestone 0 — Project scaffolding
- [x] T0.1 Create `pyproject.toml` (package `t2pbi`, deps: lxml, pyside6; dev: pytest, pyinstaller).
- [x] T0.2 Create `t2pbi/` skeleton + empty modules per Technical Design §3.
- [ ] T0.3 Add `.claudeignore` (`.venv/`, `dist/`, `build/`, `*.twbx` fixtures if large).
- [x] T0.4 Set up `pytest` + a trivial smoke test that imports the package.

## Milestone 1 — Extract & Parse (read Tableau)
- [x] T1.1 `core/extract.py`: detect `.twb` vs `.twbx`; stream-locate `.twb` in the zip; map resources. Reject invalid files early.
- [x] T1.2 `ir/model.py`: define the IR dataclasses (Workbook, DataSource, Table, Column, Worksheet, Dashboard, ConversionFlag).
- [x] T1.3 `core/parse/datasources.py`: parse tables, columns, datatypes, roles, calculated-field formulas, relationships.
- [x] T1.4 `core/parse/worksheets.py`: parse visual type + encodings (rows/cols/marks) + filters.
- [x] T1.5 `core/parse/dashboards.py`: parse dashboard → contained sheets.
- [x] T1.6 Golden fixtures: add 2–3 sample `.twb`/`.twbx` files + parse snapshot tests.

## Milestone 2 — Map to Power BI IR
- [ ] T2.1 `core/mapping/model_map.py`: Tableau model → PBI model IR (tables/columns/rels, name sanitization, record renames as flags).
- [x] T2.2 `core/mapping/visual_map.py`: Tableau viz → PBI visual IR for the v1 visual set; flag unmapped types.

## Milestone 3 — DAX translation
- [x] T3.1 `core/dax/functions.py`: data-driven supported-function/pattern table (start with the agreed v1 list).
- [x] T3.2 `core/dax/translator.py`: parse Tableau calc → translate only if fully supported; else placeholder + flag.
- [x] T3.3 Fixture suite of calc→DAX pairs (the correctness backbone).

## Milestone 4 — Generate PBIP
- [x] T4.1 `core/emit/tmdl.py`: write `.SemanticModel` TMDL (tables, columns, measures, relationships).
- [x] T4.2 `core/emit/pbir.py`: write `.Report` PBIR visuals from the visual IR.
- [x] T4.3 `core/emit/pbip.py`: scaffold the `.pbip` + folders; deterministic GUIDs from names.
- [ ] T4.4 Golden-snapshot tests of generated TMDL/PBIR.
- [ ] T4.5 Manual: open a generated PBIP in Power BI Desktop — no repair errors.

## Milestone 5 — Report & Pipeline
- [x] T5.1 `core/report.py`: aggregate ConversionFlags → `migration-report.{json,html}`.
- [x] T5.2 `pipeline.py`: orchestrate stages 1–6; the only owner of stage order.
- [x] T5.3 `cli.py`: `t2pbi convert <input> --out <dir>`.

## Milestone 6 — Desktop app
- [x] T6.1 `desktop/worker.py`: run `pipeline.run()` on a QThread; emit progress.
- [x] T6.2 `desktop/app.py`: pick input → pick output → Convert → progress → open report/PBIP.
- [x] T6.3 `packaging/`: PyInstaller spec → single Windows `.exe`.

## Milestone 7 — Validation against the Spec
- [ ] T7.1 Run every Acceptance Criterion in the Spec Doc §6; record pass/fail.
- [x] T7.2 Performance check: representative workbook converts < 30s locally.
- [x] T7.3 Determinism check: same input → byte-identical output.
