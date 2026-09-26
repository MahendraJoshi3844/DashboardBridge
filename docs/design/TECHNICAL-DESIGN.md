# Technical Design Plan — Tableau → Power BI Migration (v1)

> **Type:** Technical Design Plan (the *How*). Pairs with
> `docs/specs/SPEC-tableau-to-powerbi-migration.md` (the *Why/What*).
> Per SDD: if the stack ever changes, only this document is rewritten.
>
> **Status:** Draft v1 · **Last updated:** 2026-06-19

---

## 1. Chosen Stack & Rationale

| Decision | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | Best XML/ZIP ecosystem, fastest to iterate, matches both reference repos, strong data tooling. |
| XML parsing | **lxml** (C-backend) + `iterparse` for big files | Fast, streaming-capable; avoids loading whole `.twb` into a DOM when not needed. |
| Archive handling | stdlib **`zipfile`** | `.twbx` is a ZIP; read members lazily, never extract whole archive. |
| Output model format | **PBIP** with **TMDL** (semantic model) + **PBIR** (report) | Microsoft's open, text-based, git-friendly project format. |
| Phase-2 packaging | **`.pbix`** writer | Built on top of the PBIP artifacts later. |
| Desktop UI | **PySide6 (Qt)** | Native, fast, offline; clean threading so UI never blocks during convert. |
| Packaging | **PyInstaller** → single Windows installer | Ships a self-contained `.exe`; no Python install needed by customer. |
| Testing | **pytest** + golden-file fixtures | Deterministic snapshot tests of generated TMDL/PBIR. |

**Performance principles (the user's stated top priority):**
1. **Stream, don't slurp.** Parse `.twb` XML with `iterparse`; read only the schema
   from extracts — never materialize full data.
2. **Single pass where possible.** Build an in-memory Intermediate Representation
   (IR) in one traversal, then generate output from the IR.
3. **No network. No surprises.** Pure local CPU/IO; deterministic output.
4. **Parallelizable stages are isolated** behind the IR so they can be threaded if a
   workbook is huge, without changing the contract.

---

## 2. Architecture — Pipeline + Intermediate Representation

The core is a **linear pipeline** around a single, well-typed **Intermediate
Representation (IR)**. The IR is the seam that keeps "read Tableau" decoupled from
"write Power BI" — the same idea that lets the spec survive a stack change.

```
 .twb / .twbx
      │
      ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ 1. EXTRACT   │──▶│ 2. PARSE     │──▶│  IR (model)  │──▶│ 3. MAP        │
│ unzip/locate │   │ lxml → raw   │   │  dataclasses │   │ Tableau→PBI   │
└──────────────┘   └──────────────┘   └──────────────┘   └──────┬───────┘
                                                                │
   ┌────────────────────────────────────────────────────────────┘
   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ 4. TRANSLATE │──▶│ 5. GENERATE  │──▶│ 6. REPORT    │
│ calc → DAX   │   │ TMDL + PBIR  │   │ migration md │
└──────────────┘   └──────────────┘   └──────────────┘
        │                  │                  │
        ▼                  ▼                  ▼
   flagged items      PBIP folder       migration-report.{html,json}
```

### Stage responsibilities

| # | Stage | Input | Output | Module |
|---|---|---|---|---|
| 1 | **Extract** | `.twbx`/`.twb` path | path to `.twb` + resource map | `core/extract.py` |
| 2 | **Parse** | `.twb` XML | raw parsed structures | `core/parse/` |
| 3 | **Map** | raw structures | IR model (tables, cols, rels, visuals) | `core/mapping/` |
| 4 | **Translate** | Tableau calc strings | DAX strings + flags | `core/dax/` |
| 5 | **Generate** | IR | PBIP (TMDL + PBIR) | `core/emit/` |
| 6 | **Report** | flags from all stages | migration report | `core/report.py` |

### The IR (heart of the system)
Plain Python `@dataclass` objects, e.g.:
```
Workbook(datasources, dashboards, version)
  DataSource(name, connection, tables[])
    Table(name, columns[], relationships[])
      Column(name, datatype, role[dimension|measure], formula?)
  Worksheet(name, visual_type, encodings{rows,cols,marks}, filters[])
  Dashboard(name, items[])
ConversionFlag(item, severity, reason)   # feeds the report
```
Every stage reads/writes only the IR — never another stage's internals.

---

## 3. Module / Folder Layout

```
t2pbi/
  __init__.py
  cli.py                 # headless entry point (also used by desktop + tests)
  pipeline.py            # orchestrates stages 1–6; the only place order lives
  ir/                    # Intermediate Representation dataclasses
    model.py
  core/
    extract.py           # .twbx → .twb + resources (streaming zip)
    parse/
      datasources.py     # tables, columns, connections, relationships
      worksheets.py      # visuals, encodings, filters
      dashboards.py      # layout containers
    mapping/
      model_map.py       # Tableau model → PBI model IR
      visual_map.py      # Tableau viz → PBI visual IR
    dax/
      translator.py      # Tableau calc → DAX
      functions.py       # supported-function table (data-driven)
    emit/
      tmdl.py            # write .SemanticModel TMDL files
      pbir.py            # write .Report PBIR (visuals)
      pbip.py            # write .pbip + folder scaffolding
    report.py            # migration report (html + json)
  desktop/
    app.py               # PySide6 main window
    worker.py            # runs pipeline on a QThread; emits progress
tests/
  fixtures/              # sample .twb/.twbx inputs
  golden/                # expected TMDL/PBIR snapshots
  test_*.py
```

**Rule:** `pipeline.py` is the *only* module that knows the stage order. The desktop
app and CLI both call `pipeline.run(input, output, options)` — UI is a thin shell.

---

## 4. Key Technical Decisions

### 4.1 Why PBIP/TMDL (not PBIX) first
- PBIX is undocumented and brittle; TMDL/PBIR are **text, documented, diffable**.
- Generating text files is far simpler to test (golden snapshots) and to keep
  deterministic. PBIX export becomes a downstream packaging step in Phase 2.

### 4.2 DAX translation strategy (data-driven, honest)
- A **function/pattern table** (`dax/functions.py`) maps each supported Tableau
  construct to a DAX template. Examples: `SUM([x])→SUM(...)`, `IF/THEN/ELSE→IF()`,
  `ZN→COALESCE(...,0)`, `DATEDIFF`, simple `FIXED` LOD → `CALCULATE`.
- An expression is translated **only if every node is supported**. Otherwise it is
  emitted as a commented placeholder measure and a `ConversionFlag(severity=manual)`
  is raised. **We never emit guessed DAX.** (Fidelity-over-guesswork, per spec §4.)
- The supported list is versioned; growing it is the main lever for fidelity over
  releases.

### 4.3 Visual mapping (v1 set)
A small declarative table maps Tableau mark/viz types to Power BI `visualType` +
field-well bindings: bar, line, area, table/matrix, KPI/card, scatter, pie. Anything
else → closest match + flag.

### 4.4 Determinism
- Stable ordering everywhere (sorted keys, no set iteration in output).
- No timestamps/random ids in generated files except where PBIP requires a GUID —
  those are derived **deterministically** from item names (hash), not random.

### 4.5 Threading model (desktop)
- Pipeline runs on a `QThread` worker; emits `progress(stage, pct)` signals.
- UI thread only renders — guarantees the app never freezes on a big workbook.

---

## 5. Migration Report
- Built from the `ConversionFlag` list accumulated across all stages.
- `migration-report.json` = machine-readable (for future SaaS dashboards).
- `migration-report.html` = self-contained, customer-facing summary:
  totals, per-table/field/visual status, and a clear "needs manual work" section.

---

## 6. Build / Run / Test Commands

```bash
# Environment
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"

# Convert (headless)
t2pbi convert path/to/workbook.twbx --out ./output

# Run the desktop app
python -m t2pbi.desktop.app

# Tests
pytest                       # all
pytest tests/test_dax.py     # one file
pytest -k translate_if       # one test by name
pytest --snapshot-update     # refresh golden TMDL/PBIR snapshots

# Package the desktop app (Windows)
pyinstaller packaging/t2pbi.spec
```

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Tableau XML varies across versions | Version-detect + golden fixtures from multiple Tableau versions; warn on untested versions. |
| PBIP/PBIR format evolves | Isolate all format knowledge in `emit/`; pin a certified Power BI Desktop version. |
| DAX translation correctness | Strict "translate only if fully supported"; fixture-tested; everything else flagged, never guessed. |
| Performance on huge extracts | Stream zip + schema-only reads; never load extract data. |
| Scope creep into full-fidelity layout | Spec explicitly defers layout/LOD/params to roadmap. |

---

## 8. Phase Roadmap (engineering)

- **Phase 1 (v1):** pipeline + IR, model + fields + supported DAX + basic visuals +
  report + desktop app + PBIP output. *(this design)*
- **Phase 2:** `.pbix` packaging; expand supported DAX function set; more visuals.
- **Phase 3:** dashboard layout fidelity; parameters/actions; LOD coverage.
- **Phase 4:** optional SaaS wrapper reusing the same `pipeline.run()` core.
