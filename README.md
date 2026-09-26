# DashboardBridge

One web application for migrating BI content to **Power BI**, over separately
sold conversion engines. A customer licenses any combination:

| Product | Engine | Repository |
|---|---|---|
| **Tableau → Power BI** (and Power BI → Tableau) | `t2pbi` | Tableau-to-Power-BI |
| **MicroStrategy → Power BI** | `mstr2pbi` | MicroStrategy-to-Power-BI |
| **Qlik → Power BI** | `qlik2pbi` | Qlik-To-PowerBI |

This repository is the shell (UI, API, contracts, licensing, validation). It
contains no engine: each is an optional install, pinned by commit.

- **Delivery:** a web application the customer runs in their own environment.
  Licensed offline; air-gapped installs are a normal case.
- **Stack:** Python 3.14 (FastAPI, SQLAlchemy) + Next.js 15 / React 19.
- **Output:** PBIP (TMDL + PBIR) for Power BI; `.twb` for Power BI → Tableau.

## Who can use what

A migration path shows as usable only when its engine is **installed** on the
deployment, **included in the licence**, and **granted to the person**.
Administrators see every installed, licensed path and decide under
**Administration → Users & access** who may use Tableau, MicroStrategy and/or
Qlik. Everyone else sees the paths they were not given as locked, with the
reason.

```bash
pip install -r apps/api/requirements.txt
pip install -r apps/api/requirements-engine-tableau.txt        # each engine the customer bought
pip install -r apps/api/requirements-engine-microstrategy.txt
pip install -r apps/api/requirements-engine-qlik.txt
```

With Docker: `ENGINES="tableau qlik" docker compose up` (default: all three).

## Documentation
| Doc | Purpose |
|---|---|
| [`SPEC.md`](SPEC.md) | Master specification |
| [`docs/dashboardbridge/00-decisions.md`](docs/dashboardbridge/00-decisions.md) | Decisions (ADRs) |
| [`docs/dashboardbridge/11-roadmap.md`](docs/dashboardbridge/11-roadmap.md) | Roadmap |
| [`docs/operations/RUNBOOK.md`](docs/operations/RUNBOOK.md) | Running it as a customer would |
| [`docs/business/PRODUCT-VISION.md`](docs/business/PRODUCT-VISION.md) | Pitch / business vision |
| [`AGENTS.md`](AGENTS.md), [`CLAUDE.md`](CLAUDE.md) | How to work on it |

## Run it

```powershell
pwsh scripts/run-local.ps1
```

Then open <http://localhost:3000> and sign in with the account it prints. The
script creates a development licence, migrates the database and starts both
halves; `-Reset` starts from an empty deployment.

`testing_content/Superstore.twb` is there to try (or any file in
`tests/fixtures/`). The screens:

- **Migrate** (`/migrate`) — pick a migration path; Tableau → Power BI opens the
  upload dialog. **Start Migration** creates the job and sends the workbook.
- **Job detail** (`/jobs/<id>`) — status, migration settings, and the
  **Migration Logs**: each step as its request returns, then the engine's own
  recording of every object it handled. **Files** and **Power BI Model** tabs
  show the produced project. Download the `.pbip`, or open it in the workspace.
- **Power BI workspace** (`/workspace/powerbi/<id>`) — edit measure DAX and
  table Power Query, write DAX for calculations the converter held, check DAX
  references, run validation, and save the edits as a new version. The
  download always serves the newest version.
  **Report Explorer** (rail, after M-Query) lists every page and visual that
  came across, each with its Tableau worksheet, mark type, fields and the
  converter's notes. Nothing is ticked by default; the `.pbip` export carries
  the full semantic model and only the ticked visuals.
  **Run menu / AI Chat**: Optimize Model, Validate Calculations, Validate &
  Fix DAX, Validate & Fix M-Query, Full Health Check, and Batch Fix DAX /
  M-Query / All. Each job runs as tasks shown in the AI Chat tab as they
  return. Deterministic checks run first (references, `DIVIDE()` rewrites,
  placeholder sources, unused columns, untyped columns, possible missing
  relationships); a model is asked only to draft DAX for held calculations,
  to summarise, and to answer chat. Every proposed change is applied by a
  person into draft changes, never automatically.
- **Migration Jobs** (`/jobs`) — every job, with status and resume.

### Local AI (optional)

With [Ollama](https://ollama.com) running on this machine and `llama3.1`
pulled, start the API with:

```powershell
$env:AI_PROVIDER = "ollama"; $env:AI_MODEL = "llama3.1"; $env:AI_TIMEOUT_S = "180"
```

Only a loopback address is accepted, so nothing leaves the machine. On a CPU
an answer takes roughly 30 seconds to 2 minutes. Model drafts are checked
twice — the proposal gauntlet, then against this model's own tables and
measures — and are discarded with the reason when they fail.

The guided single-screen flow is still at `/classic`.

`run-local.ps1` needs PowerShell 7 (`pwsh`); under Windows PowerShell 5.1 it
stops at the database step because alembic logs to stderr.

Headless, without the web app, each engine has its own command line
(`t2pbi convert`, `mstr2pbi convert`, `qlik2pbi convert`) in its own repository.

## Status

**Phases 0-8 are built** except the two acceptance criteria that need software
this machine does not have. Working end to end: upload → analyse → convert →
validate → download → report, behind accounts and an offline licence.

On Superstore (267 objects): **140 converted, 17 partial, 104 unsupported, 0
failed**, and 188 flags of which 110 are real manual work. Those numbers are the
product's own report about itself, and the denominator counts every object
*found* rather than every object attempted.

What it will not do, deliberately:

- **Guess.** An unmapped DAX function, an untyped filter member, a visual with
  no bindable field: each is refused and reported with the reason, never
  approximated into something that looks converted.
- **Read your data.** Schema only. Power BI Desktop will say some tables have no
  data, correctly; each source is reported with its kind and path so the
  connection can be repointed.
- **Carry filters into the file — yet.** They are reported with their values.
  The emitter exists and is tested against Power BI Desktop's own serializer,
  and is off until a Desktop has opened a project containing one.

Reloading the page keeps your place. The flow is remembered per browser tab, and
a run interrupted while the server was working comes back at the last step it can
honestly resume from — the configuration screen rather than a progress bar with
nothing behind it. Closing the tab ends the run.

Known gaps: no generated `.twb` has been opened by Tableau Desktop; no real
model has been run against the AI layer (everything goes through
`MockProvider`).

See [`docs/operations/RUNBOOK.md`](docs/operations/RUNBOOK.md) for running it as
a customer would - licences, accounts, model providers, privacy modes.

## Development
This project follows **Spec-Driven Development**: one feature per branch, spec →
review → design → review → tasks → build → validate. Never commit to `main`.
