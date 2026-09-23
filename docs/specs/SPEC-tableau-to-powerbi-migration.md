# Spec Document — Tableau → Power BI Migration (v1)

> **Type:** Spec Document (the *Why* + *What*). Technology-agnostic by design.
> The *How* lives in `docs/design/TECHNICAL-DESIGN.md` (see SDD standard: spec and
> technical design are kept separate so one spec can outlive a tech-stack change).
>
> **Status:** Draft v1 · **Owner:** Mahendra Joshi · **Last updated:** 2026-06-19

---

## 1. Problem Statement

Organizations that have invested years in **Tableau** dashboards increasingly want
(or are mandated) to move to **Microsoft Power BI** — usually to consolidate on the
Microsoft/Fabric stack, cut Tableau licensing cost, or unify governance.

Today that migration is **manual, slow, and expensive**:

- An analyst opens each Tableau workbook, reads every data source, field, and
  calculation, and re-creates it by hand in Power BI Desktop.
- Tableau calculated fields must be rewritten in **DAX**, a different language.
- A mid-size workbook (10–30 sheets) can take **days to weeks** to rebuild, and
  fidelity depends entirely on the analyst's skill.
- Consultancies charge large fees for exactly this rote, error-prone work.

There is no trustworthy, fast tool that takes a Tableau workbook and produces a
**ready-to-open Power BI project** that recovers most of the work automatically.

**This product automates the 80% that is mechanical**, so a human only finishes the
last 20% — turning weeks into hours.

### Who is this for?
- **BI consultancies / system integrators** running Tableau→Power BI engagements.
- **Enterprise BI teams** migrating their own estate.
- **Individual analysts** who inherited Tableau content and must move it.

---

## 2. Functional Requirements

The system **shall**:

### 2.1 Input
- Accept a single Tableau workbook file: **`.twb`** (XML) or **`.twbx`** (packaged
  archive containing the `.twb` plus extracts/resources).
- Validate that the file is a readable Tableau workbook and report its version.

### 2.2 Parse & understand the workbook
- Extract all **data sources**: connections (type, server, database), and whether
  the data is live or an extract.
- Extract all **tables / fields**: dimensions and measures, data types, names,
  captions, and folder/hierarchy groupings.
- Extract all **calculated fields** and their Tableau formula text.
- Extract **relationships / joins** between tables where defined.
- Extract each **worksheet (sheet)**: its visual type, the fields placed on
  rows/columns/marks (color, size, label, detail), filters, and sort.
- Extract each **dashboard**: which sheets it contains and their arrangement.

### 2.3 Convert (v1 scope)
- **Data model:** produce a Power BI semantic model with the tables, columns,
  data types, and relationships recovered from Tableau.
- **Fields:** map Tableau dimensions/measures to Power BI columns/measures.
- **Calculations:** translate **supported** Tableau calculated fields into **DAX**.
  Unsupported/complex expressions are carried over as a commented placeholder and
  flagged (never silently dropped).
- **Basic visuals:** recreate the common visual types — **bar, line, area, table /
  matrix, KPI/card, scatter, pie** — with their core field placements.

> **Out of scope for v1** (deferred, see §4 and Roadmap): pixel-perfect dashboard
> layout, advanced LOD expressions, table calculations, parameters/actions,
> custom Tableau visuals, and Tableau-specific formatting nuances.

### 2.4 Output
- Produce a **Power BI Project (PBIP)** folder using Microsoft's open, text-based
  format (semantic model + report), openable directly in Power BI Desktop.
- (Phase 2) Optionally package the project into a binary **`.pbix`** file.

### 2.5 Migration report
- Produce a human-readable **Migration Report** listing, per item:
  - what converted cleanly,
  - what converted with assumptions,
  - what could **not** be converted and needs manual work, with a reason.
- This report is a **first-class deliverable** — it is how a consultant scopes the
  remaining manual effort and how the product builds trust.

### 2.6 Desktop application
- Ship as an **offline desktop app**: the user picks a `.twbx`, picks an output
  folder, clicks Convert, watches progress, and opens the report + PBIP when done.
- All processing happens **locally** — no workbook ever leaves the machine.

---

## 3. Input / Output Behaviour (Contract)

| Aspect | Description |
|---|---|
| **Input** | One `.twb` or `.twbx` file selected by the user. |
| **Primary Output** | A PBIP project folder (`<name>.SemanticModel/`, `<name>.Report/`, `<name>.pbip`). |
| **Secondary Output** | A Migration Report (`migration-report.html` + `.json`). |
| **Phase-2 Output** | A `.pbix` file (binary), produced from the PBIP. |
| **Failure Output** | A clear error file/dialog stating what failed and why; no half-written project left behind. |

The **conversion is one-way and non-destructive**: the source workbook is only ever
read, never modified.

---

## 4. Constraints

- **Privacy / offline:** conversion must run fully locally; no network call with
  workbook contents. This is a core selling point for enterprise customers.
- **Performance (explicit priority):**
  - A typical workbook (≤ 25 sheets, extract ≤ 200 MB) should convert in **under
    30 seconds** on a normal laptop.
  - Parsing must stream/skip large embedded data extracts — never load an entire
    extract into memory just to read the schema.
  - Memory use should stay well under what an 8 GB laptop can spare.
- **Fidelity over guesswork:** when a translation is uncertain, the system **flags
  it in the report** rather than emitting plausible-but-wrong output.
- **Determinism:** the same input must always produce the same output (important
  for trust, testing, and re-runs).
- **Supported environment:** Windows desktop first (Power BI Desktop is Windows-only).
- **Power BI compatibility:** output must open in a current Power BI Desktop release
  without "repair" prompts.

---

## 5. Edge Cases & Error Handling

| Edge case | How to handle |
|---|---|
| File is not a valid `.twb`/`.twbx` | Reject early with a clear message; do not start conversion. |
| `.twbx` with no extract (live connection only) | Convert the model schema; note in report that data is a live connection to re-point in Power BI. |
| Very large embedded extract | Read only schema/metadata; never materialize the full extract. Note size in report. |
| Calculated field uses an unsupported function/LOD | Emit a commented placeholder measure + flag it in the report as "manual review". |
| Visual type has no clean Power BI equivalent | Map to the closest type and flag it; never crash. |
| Duplicate / illegal names for Power BI | Deterministically sanitize (and record the rename in the report). |
| Workbook from a much newer/older Tableau version | Attempt best-effort parse; warn if version is untested. |
| Zero worksheets / empty workbook | Produce a valid empty PBIP + report saying nothing convertible was found. |
| Output folder not writable / already exists | Prompt user; never overwrite without consent. |
| Partial failure mid-convert | Fail cleanly, leave no corrupt PBIP, report exactly which stage failed. |

---

## 6. Acceptance Criteria

v1 is considered **done** when:

- [ ] A user can select a `.twb` or `.twbx` file in the desktop app and produce a
      PBIP folder that **opens in Power BI Desktop without repair errors**.
- [ ] Tables, columns, data types, and relationships present in the workbook appear
      correctly in the Power BI model.
- [ ] Tableau measures/dimensions appear as the correct Power BI columns/measures.
- [ ] A defined set of **supported** Tableau calculations are translated to working
      DAX (verified against a fixture set).
- [ ] The common visual types (bar, line, area, table/matrix, KPI/card, scatter,
      pie) are recreated with their core field placements.
- [ ] Every item that could not be fully converted is **listed in the Migration
      Report** with a reason — nothing is silently dropped.
- [ ] A representative sample workbook converts in **under 30 seconds** locally.
- [ ] Re-running the same input produces an **identical** output (determinism).
- [ ] No workbook data leaves the machine during conversion.

---

## 7. Open Questions (to resolve before/within Technical Design)

1. Which exact list of Tableau functions/calc patterns are **"supported"** in v1?
   (Drives the DAX translator scope — see Technical Design.)
2. Minimum Power BI Desktop version we certify against.
3. Do we need a licensing/activation mechanism for the desktop app at launch, or is
   v1 a free/beta to gather pilot customers?
