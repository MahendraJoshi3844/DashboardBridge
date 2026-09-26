# Module Spec — Report + Pipeline + CLI

**Code:** `t2pbi/report.py`, `t2pbi/pipeline.py`, `t2pbi/cli.py`

## Purpose
Orchestrate stages 1–6 and expose them headlessly. `pipeline.py` is the **only**
module that knows the stage order.

## pipeline.run(input_path, out_dir, project_name=None) -> ConvertResult
Order:
1. `extract()` → twb bytes
2. `parse_workbook()` → Workbook IR
3. **translate step**: for each calculated column, call `translate_formula`; on
   success set `col.dax`; on failure add a MANUAL `ConversionFlag` (never guess).
4. `write_pbip()` → PBIP folder
5. `report.write_report()` → `migration-report.{json,html}`
Returns `ConvertResult(pbip_path, report_path, flags, stats)`. Deterministic.

## report.write_report(wb, out_dir)
- `migration-report.json`: `{ stats, flags[] }`.
- `migration-report.html`: self-contained summary — totals + a table of flags grouped
  by severity, with a clear "needs manual work" (MANUAL) section.

## cli.py
- `t2pbi convert <input> --out <dir> [--name <project>]`
- Prints a one-line summary (tables/measures/flags) and the output paths.
- Exit code 0 on success; non-zero with a clear message on `InvalidWorkbookError`.

## Acceptance
- End-to-end: a sample `.twb` → a PBIP folder + a report listing every flag.
- Re-running the same input yields identical files (determinism).
- Stage order exists only in `pipeline.py`.
