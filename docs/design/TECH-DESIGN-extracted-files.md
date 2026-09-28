# Technical Design — Extracted Files

> Implements `docs/specs/SPEC-extracted-files.md`. **Branches:** engine
> `feature/metadata-extraction` (Tableau-to-Power-BI), shell
> `feature/extracted-files` (DashboardBridge).

## 1. Where it lives

The files are produced by the **Tableau engine**, because only the engine has
the IR, the translation results and the produced model. The shell stores the
archive, serves it and shows it.

```
t2pbi pipeline:  Extract → Parse → Map → Translate → Generate → Report
                                                                  └─ extraction (opt-in)
```

- `t2pbi/core/report/extraction.py` builds every file from the IR, the mapped
  visuals and the produced PBIP. It reads the IR and the engine's own output
  and never re-reads the workbook XML (the stage rule).
- `t2pbi/core/report/validation.py` checks the produced PBIP:
  - it reads the TMDL table, column and measure names and the PBIR
    projections;
  - it parses every emitted DAX expression with the DAX normaliser;
  - it resolves every `'T'[C]` and `[M]` reference against the model.
- `pipeline.run(..., extraction_dir=None)` writes the extraction when a
  directory is given. The pipeline stays the only place that knows the stage
  order. The CLI gains `--extract DIR`.
- The parser records what the files need and the IR lacked:
  - `DataSource.connections`: each named connection's class, caption, server,
    database, schema, port, file and directory. Username and password are
    never read into the IR.
  - `Table.custom_sql`: the SQL text of a custom-SQL relation.

## 2. Archive layout (`schema: "dashboardbridge.extraction/1"`)

```
extracted/
  manifest.json          engine, schema version, source file name + sha256, file list, counts
  workbook.json          version, counts, tab order
  datasources.json       connections (no credentials), tables, custom SQL
  tables/<table>.json    columns: tableau name, caption, datatype, role, calculated,
                         formula, Power BI name + data type + summarize-by
  calculations.json      every calculation once: formula, kind, DAX, status, reason,
                         rule ids, depends_on
  dependency_graph.json  edges, conversion order, cycles, blocked-by-refusal
  parameters.json
  relationships.json
  worksheets.json        mark, shelves, filters; Power BI visual type + wells
  dashboards.json        size, zones
  page_mapping.json      Tableau tab -> Power BI page + its visuals/slicers
  flags.json             every conversion flag
VALIDATION_REPORT.md     human-readable, PASSED/FAILED
validation.json          the same results, machine-readable
source/<name>.twb        the workbook definition (never the extract)
powerbi/                 the PBIP project and migration-report.html
```

All JSON files are written with sorted, stable content. `json.dumps(...,
indent=2, ensure_ascii=False)` is used with list order taken from the IR,
which is itself deterministic. No timestamps appear anywhere.

## 3. Shell (DashboardBridge)

- **Seam:** `engines/conversion/run.py` passes `extraction_dir`. It copies the
  source `.twb` into `extracted/source/` and the PBIP into
  `extracted/powerbi/`. `ConversionOutcome.extraction_dir` is set when
  produced.
- **Storage:** conversion stores a second artifact of kind `extraction`
  (`<name>.extracted.zip`) beside the target.
- **API:**
  - `GET /projects/{id}/extraction` serves the zip; a 404 with a plain message
    when the direction produced none.
  - `GET /projects/{id}/validation-report` serves the Markdown.
  - `GET /projects/{id}/files` lists what is downloadable (kind, name, size),
    which is what the Files tab renders.
- **Recompile** is `POST /projects/{id}/conversion` again: it already
  re-converts the stored source with the accepted proposals.
- **Web:** the JobDetail Files tab shows a download list above the existing
  file browser:
  - Extracted Files (.zip)
  - Power BI project (.pbip.zip)
  - Validation report (.md)

  Each has Download; the list has one Recompile. A direction with no
  extraction shows the plain statement from FR7.

## 4. Tests

- **Engine:**
  - extraction on the synthetic workbooks: every file present; every
    calculation exactly once; no credential keys; byte-identical across two
    runs;
  - validation passes on real output and fails, naming the reference, on a
    corrupted TMDL.
- **Shell:**
  - the API stores and serves the extraction;
  - `/files` lists it;
  - MicroStrategy and Qlik answer 404 with the message;
  - web unit test for the Files list.
