# t2pbi — Tableau → Power BI Migration

Convert Tableau workbooks (`.twb` / `.twbx`) into ready-to-open **Power BI projects
(PBIP)** — fully offline. Automates the ~80% mechanical work of a Tableau→Power BI
migration and flags the rest in a Migration Report.

- **Delivery:** a **web application the customer runs in their own environment**,
  around a reusable conversion engine. Licensed offline; air-gapped installs are
  a normal case.
- **Stack:** Python 3.14 (lxml, FastAPI, SQLAlchemy) + Next.js 15 / React 19
- **Output:** PBIP (TMDL + PBIR) now; `.pbix` packaging later
- **v1 scope:** data model + fields + supported calcs→DAX + basic visuals

## Documentation
| Doc | Purpose |
|---|---|
| [`docs/specs/SPEC-tableau-to-powerbi-migration.md`](docs/specs/SPEC-tableau-to-powerbi-migration.md) | Spec (Why/What) |
| [`docs/design/TECHNICAL-DESIGN.md`](docs/design/TECHNICAL-DESIGN.md) | Technical Design (How) |
| [`docs/TASKS.md`](docs/TASKS.md) | Implementation tasks |
| [`docs/business/PRODUCT-VISION.md`](docs/business/PRODUCT-VISION.md) | Pitch / business vision |
| [`CLAUDE.md`](CLAUDE.md) | Guidance for Claude Code |

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
- **Migration Jobs** (`/jobs`) — every job, with status and resume.

The guided single-screen flow is still at `/classic`.

`run-local.ps1` needs PowerShell 7 (`pwsh`); under Windows PowerShell 5.1 it
stops at the database step because alembic logs to stderr.

Headless, without the web app:

```bash
t2pbi convert testing_content/Superstore.twb --out ./output
```

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
