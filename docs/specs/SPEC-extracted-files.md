# Spec Document — Extracted Files for a migration job

> **Type:** Spec Document (the *Why* + *What*). Technology-agnostic by design.
> The *How* is in `docs/design/TECH-DESIGN-extracted-files.md`.
>
> **Status:** Draft for review · **Owner:** Mahendra Joshi ·
> **Last updated:** 2026-09-28 · **Branch:** `feature/extracted-files`

---

## 1. Problem Statement

A migration job today hands back two things: the converted Power BI project and
an HTML migration report. What the tool *read* from the workbook, and how it
decided what each thing became, is visible only inside the tool, one screen at
a time.

Consultants migrating for a client need that picture as files. They review the
workbook's metadata (data sources, tables, calculations, parameters, sheets,
dashboards) outside the tool. They check each calculation's DAX against its
Tableau formula. They attach a validation report to the delivery, and they
diff the files between runs. Competing tools ship this as a downloadable
"Extracted Files" archive on the job page. Without one, DashboardBridge looks
like a black box at exactly the point where a buyer is deciding whether to
trust it.

**Goal:** every Tableau → Power BI job offers an **Extracted Files** archive.
It holds the workbook's metadata as machine-readable files, what each item
became in Power BI, and a validation report that checks the produced model.
Every statement in it is derived from what was read or produced, never
estimated.

## 2. Functional Requirements

**FR1 — Files tab lists downloads.** After a job converts, its Files tab offers:

- **Extracted Files (.zip)**: the archive defined below.
- **Power BI project (.pbip.zip)**: the project itself.
- **Validation report**: readable on its own, without unzipping.

Each entry has a Download action. The existing file-by-file browser of the
project remains.

**FR2 — Recompile.** The Files tab offers **Recompile**. It re-runs the
conversion of the same uploaded workbook, with the same accepted proposals,
and refreshes every download. Nothing is re-uploaded.

**FR3 — Metadata extracted from the workbook.** The archive describes, as read
from the workbook:

- **The workbook:** version, and counts of data sources, tables, columns,
  calculations, parameters, worksheets and dashboards.
- **Each data source:** connection type, server, database, file, tables and
  custom SQL. Passwords and credentials are never included.
- **Each table and column:** Tableau name, caption, data type and role.
- **Each calculation:** its Tableau formula, its kind, and what it depends on.
- **Parameters:** type, default, range or list.
- **Relationships.**
- **Each worksheet:** mark type, the fields on each shelf, and filters.
- **Each dashboard:** size, and the zones with their positions.

**FR4 — What each item became.** Beside the metadata, the archive records:

- **For each calculation:** its Power BI name, whether it is a measure or a
  calculated column, the DAX, and its status (converted, or refused with the
  reason).
- **For each column:** its Power BI name and data type.
- **For each Tableau tab:** the Power BI page it became.
- **For each worksheet:** the Power BI visual type and the fields in each well.
- **Every conversion flag:** severity, stage and reason.
- **The dependency order of calculations:** any cycle is named.

**FR5 — Validation report.** A report checks the produced model and states
PASSED or FAILED:

- Every emitted DAX expression is readable DAX.
- Every table, column and measure it references exists in the produced model.
- Every field a report visual uses exists in the model, as the right kind
  (column or measure).
- It summarises calculations: totals, converted, refused (with reasons),
  invalid.
- It gives a per-table schema overview (columns, measures).

A refused calculation is not a failure; it is reported work. FAILED means the
produced project contains something broken.

**FR6 — Source workbook included.** The archive includes the workbook
definition that was read. It never includes the data extract or any data rows.

**FR7 — Other directions.** For directions whose engine does not produce
extracted files, the Files tab says so plainly and still offers the project
download. No empty or fabricated archive is served.

## 3. Non-Functional Requirements

- **NFR1 — Deterministic.** The same workbook produces byte-identical
  metadata files. There are no timestamps or random identifiers in the files.
- **NFR2 — Offline and private.** Nothing leaves the machine, and credentials
  are never written.
- **NFR3 — Fast.** Producing the archive adds under 2 seconds to a typical
  conversion.
- **NFR4 — Honest.** Every count in every file is computed from what was read
  or produced. The validation status is FAILED whenever any check fails.
- **NFR5 — Versioned format.** Every metadata file carries a schema version,
  so consumers can detect changes.

## 4. Acceptance Criteria

1. Converting `Superstore_V1.twbx` shows Extracted Files, Power BI project and
   Validation report in the Files tab, and each downloads.
2. The extracted archive contains:
   - one file per area in FR3 and FR4;
   - one file per table;
   - the validation report;
   - the source workbook definition;
   - no data extract.
3. Every calculation in the workbook appears in the calculations file exactly
   once, as converted with DAX or refused with a reason.
4. The validation report on Superstore and on the Grid Quality reference
   passes, with every reference checked. A deliberately broken reference makes
   it FAIL and names the reference.
5. Two conversions of the same workbook produce identical metadata files.
6. Recompile produces a new archive without a new upload.
7. A MicroStrategy or Qlik job's Files tab states that extracted files are not
   available for that direction and still offers the project download.

## 5. Assumptions (to confirm in review)

- Extraction runs as part of conversion. Every job converts, so the uploaded
  workbook's metadata is available from the first run.
- The file set is DashboardBridge's own, designed for this product. It covers
  the reference tool's content, but it does not copy its file names or
  structure.
- MicroStrategy and Qlik extraction is a later feature for those engines.
