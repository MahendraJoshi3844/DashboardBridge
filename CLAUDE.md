# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**t2pbi** converts **Tableau** workbooks (`.twb` / `.twbx`) into **Power BI**
projects (PBIP). It is an **offline Windows desktop app** plus a reusable conversion
engine. Goal: automate the ~80% mechanical work of a Tableau→Power BI migration and
flag the rest, turning weeks of manual rebuild into hours.

This is an early-stage **startup product** intended to be pitched to BI consultancies
and enterprise BI teams. Trust and fidelity matter as much as features.

- **Spec (Why/What):** `docs/specs/SPEC-tableau-to-powerbi-migration.md`
- **Technical Design (How):** `docs/design/TECHNICAL-DESIGN.md`
- **Tasks:** `docs/TASKS.md`
- **Business / pitch:** `docs/business/PRODUCT-VISION.md`

## Architecture (big picture)

A **6-stage linear pipeline** around a single **Intermediate Representation (IR)**:

`Extract → Parse → [IR] → Map → Translate(DAX) → Generate(PBIP) → Report`

- The **IR** (`t2pbi/ir/model.py`) is the seam: "read Tableau" never touches
  "write Power BI". Each stage only reads/writes the IR.
- `t2pbi/pipeline.py` is the **only** module that knows the stage order. Both the
  CLI (`cli.py`) and the desktop app call `pipeline.run(input, output, options)`; the
  UI is a thin shell.
- Every non-perfect conversion produces a **ConversionFlag**, which feeds the
  customer-facing **Migration Report**. Nothing is ever silently dropped.

See `docs/design/TECHNICAL-DESIGN.md` §2–§3 for the stage table and folder layout.

## Engines are separate products

DashboardBridge is one UI/API over separately sold engines. Customers buy any
combination, so no engine may be required by another or by the shell:

| Direction | Engine | Repository | Install | Licence feature |
|---|---|---|---|---|
| Tableau ↔ Power BI | `t2pbi` | this repo (`t2pbi`) | always | `tableau` |
| MicroStrategy → Power BI | `mstr2pbi` | MicroStrategy-to-Power-BI | `pip install ".[microstrategy]"` / `requirements-engine-microstrategy.txt` | `microstrategy` |
| Qlik → Power BI | `qlik2pbi` | Qlik-To-PowerBI | `pip install ".[qlik]"` / `requirements-engine-qlik.txt` | `qlik` |

- `engines/conversion/directions.py` is the single registry: a direction is
  *available* only when its engine is importable **and** licensed. A licence naming
  no engine feature covers every installed engine (older licences keep working).
- The API refuses unavailable directions at project creation, analysis and conversion
  (`app/core/directions.py`); `GET /directions` feeds the web app's cards and sidebar.
- Optional engines are imported lazily (inside functions), their seams are
  `engines/conversion/from_*.py`, and their tests `importorskip` the engine.
- CI runs the full suite twice: with every engine, and core-only (no optional engines).
- Engines are pinned by commit in both `pyproject.toml` (extras) and
  `apps/api/requirements-engine-*.txt`; bump both together. Docker: `ENGINES="microstrategy qlik"`.
- Engine seams run with `placeholders=False` (rule 1). Local dev:
  `pip install -e ../../Mstr2PBI/MicroStrategy-to-Power-BI -e ../../Qlik2PBI/Qlik-to-Power-BI`.

## Commands

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
t2pbi convert path/to/workbook.twbx --out ./output   # headless convert
python -m t2pbi.desktop.shell                 # desktop app
pytest                                                # all tests
pytest -k <name>                                      # single test
pytest --snapshot-update                              # refresh golden TMDL/PBIR
pyinstaller packaging/t2pbi.spec                      # build Windows .exe
```
(These are the intended commands; scaffolding tasks in `docs/TASKS.md` create them.)

## Critical rules / things to avoid

- **Never emit guessed DAX or guessed visuals.** Translate only when *fully*
  supported; otherwise emit a commented placeholder + a ConversionFlag. Fidelity
  over guesswork is the product's trust contract.
- **Performance is a first-class requirement.** Stream-parse XML (`lxml.iterparse`),
  read zip members lazily, and **never load a full data extract** — only its schema.
  Target: typical workbook converts in < 30s locally.
- **Determinism.** Same input → identical output. Stable ordering; deterministic
  GUIDs derived from names, never random/timestamped.
- **Offline only.** No workbook content may leave the machine. No network calls in
  the conversion path.
- **Keep the pipeline order in `pipeline.py` only.** Don't let stages call each other.
- **Output format:** PBIP (TMDL + PBIR) now; `.pbix` packaging is Phase 2 — keep all
  format knowledge inside `core/emit/`.

## Workflow standards (from the team's Instructions guide — Spec-Driven Development)

1. **One feature per session / branch.** Always work on a feature branch, never on
   `main`. Standing rule: after pulling from git, create a **new branch**, then push.
2. **Spec-Driven Development:** write/确认 the spec → review → technical design →
   review → tasks → build → validate against the Spec's Acceptance Criteria.
3. Keep the **Spec Doc tech-agnostic**; put stack details only in the Technical
   Design. One spec can outlive a stack change.
4. Use **subagents** for isolated/exploratory work to protect the main context
   window (see `.claude/agents/`). Commit at each milestone.

## Reference (for ideas only — do NOT copy)
- https://github.com/cyphou/Tableau-To-PowerBI
- https://github.com/natezim/twbx-powerbi-converter
