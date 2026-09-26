# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**DashboardBridge** is one web application (UI + API) over **separately sold BI
migration engines**. A customer buys any combination of them; this repository is
the shell they all plug into. It contains no engine.

| Product | Engine | Repository | Install | Licence feature |
|---|---|---|---|---|
| Tableau ↔ Power BI (both directions) | `t2pbi` | Tableau-to-Power-BI | `pip install ".[tableau]"` / `requirements-engine-tableau.txt` | `tableau` |
| MicroStrategy → Power BI | `mstr2pbi` | MicroStrategy-to-Power-BI | `pip install ".[microstrategy]"` / `requirements-engine-microstrategy.txt` | `microstrategy` |
| Qlik → Power BI | `qlik2pbi` | Qlik-To-PowerBI | `pip install ".[qlik]"` / `requirements-engine-qlik.txt` | `qlik` |

It is an early-stage **startup product** pitched to BI consultancies and enterprise
BI teams, and customers run it in their own environment (offline licence; air-gapped
installs are normal). Trust and fidelity matter as much as features.

- **Master spec:** `SPEC.md`; corrections in `docs/dashboardbridge/00-decisions.md`
- **Working rules:** `AGENTS.md` (outranks habit)
- **Roadmap:** `docs/dashboardbridge/11-roadmap.md`
- **Operations:** `docs/operations/RUNBOOK.md`
- **Business / pitch:** `docs/business/PRODUCT-VISION.md`

## Architecture (big picture)

- `apps/web`: Next.js 15 / React 19 UI. `apps/api`: FastAPI gateway (SQLAlchemy,
  alembic). `packages/contracts`: Pydantic contracts; the web app's TS types are
  generated from them (`python packages/contracts/export_schema.py`, `npm run gen:types`).
- `engines/`: the shell's own layer. `adapters/` maps an engine's IR to the
  canonical contracts, `conversion/` holds the seams that run an engine,
  `validation/`, `ai/` (router, providers), `licensing/`.
- **Seams:** the only modules that import an engine at module level are
  `engines/adapters/tableau.py`, `engines/conversion/run.py`,
  `engines/conversion/from_microstrategy.py` and `engines/conversion/from_qlik.py`.
  Everything else imports them lazily, after `directions` says the engine is
  installed. `tests/dashboardbridge/test_layering.py` enforces this.
- Engines share `engines/conversion/engine_outcome.py`, `outcome.py` and
  `events.py`. The Power BI → Tableau writer (`to_tableau.py`, `adapters/tableau_emit.py`)
  lives in the shell but is part of the Tableau product: it needs `t2pbi` and the
  `tableau` feature.

## Access: installed, licensed, granted

`engines/conversion/directions.py` is the single registry. A direction is
**available** to a person only when all three hold:

1. its engine is **installed** (importable);
2. it is **licensed** (a licence naming no engine feature covers every installed engine);
3. it is **granted** to that person (`user_products`; administrators see everything
   installed and licensed, and choose who gets what under Administration → Users & access).

The API refuses otherwise at project creation, analysis and conversion
(`app/core/directions.py`: 400 not installed, 402 not licensed, 403 not granted).
`GET /directions` feeds the web app's cards and sidebar.

## Commands

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r apps/api/requirements.txt pytest httpx
# engines, from local clones (or: pip install -e ".[engines]" for the pinned commits)
pip install -e ../../Tb2PBI/Tableau-engine-only -e ../../Mstr2PBI/MicroStrategy-to-Power-BI -e ../../Qlik2PBI/Qlik-to-Power-BI
pytest                        # all tests
pytest -k <name>              # single test
pwsh scripts/run-local.ps1    # API + web app on localhost:3000
cd apps/web && npm test       # web unit tests
```

CI runs the suite twice: with every engine, and **core-only** (no engine installed).
A test that drives a real conversion marks what it needs (`tests/support/engines.py`:
`needs_tableau`; the MicroStrategy and Qlik suites `importorskip` their engine).
Anything else must pass in both shapes.

Engines are pinned by commit in `pyproject.toml` (extras) **and**
`apps/api/requirements-engine-*.txt`; bump both together. Docker installs the
engines named in `ENGINES` (default `"tableau microstrategy qlik"`).

## Critical rules / things to avoid

- **Never emit guessed DAX or guessed visuals.** Engine seams run with
  `placeholders=False`; anything not translated faithfully is refused and flagged.
- **Never import an engine outside its seam**, and never vendor an engine's code here.
  Engines import nothing from this repository (checked in each engine's own CI).
- **Commit before responding.** FastAPI runs yield-dependency teardown after the
  response is sent, so endpoints that write call `session.commit()` themselves.
- **Determinism.** Same input → identical output.
- **Offline only.** No workbook content leaves the machine; model providers are
  loopback-only unless a customer configures otherwise.

## Workflow standards (Spec-Driven Development)

1. **One feature per session / branch.** Never commit to `main`. After pulling,
   create a new branch, then push.
2. Spec → review → technical design → review → tasks → build → validate against the
   acceptance criteria. Tests first.
3. Keep specs tech-agnostic; stack details belong in the design.
4. Use subagents (`.claude/agents/`) for isolated work. Commit at each milestone.
