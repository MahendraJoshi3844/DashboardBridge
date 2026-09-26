# DashboardBridge AI — Specification

**Version:** 1.0 · **Status:** development-ready

> **Understand before you convert. Convert deterministically where possible.
> Use AI only when necessary. Validate everything.**

An explainable BI migration platform that analyses, maps, converts and validates
dashboards between Tableau and Power BI — with deterministic engineering at its
core and AI only where it adds value.

Not a file converter. The user never uploads a file and receives an unexplained
output; every step is observable and auditable.

---

## Read in this order

| # | Document | What it settles |
|---|---|---|
| 0 | [`docs/dashboardbridge/00-decisions.md`](docs/dashboardbridge/00-decisions.md) | **Corrections to this spec. Read first.** |
| 1 | `SPEC.md` (this file) | Product, principles, scope |
| 2 | [`docs/dashboardbridge/04-canonical-model.md`](docs/dashboardbridge/04-canonical-model.md) | The seam every platform crosses |
| 3 | [`docs/dashboardbridge/11-roadmap.md`](docs/dashboardbridge/11-roadmap.md) | What to build, in order |
| 4 | [`AGENTS.md`](AGENTS.md) | How to work here |
| 5 | [`CLAUDE.md`](CLAUDE.md) | Repo conventions, existing engine |

Still to be written: `02-architecture`, `03-ux-spec`, `05-api-spec`,
`06-conversion-engine`, `07-ai-engine`, `08-validation-engine`, `09-security-spec`,
`10-testing-strategy`. Their content is currently carried by this file and the
roadmap; they are extracted as each phase needs them.

---

## What already exists

This is a **re-platforming, not a greenfield build** (ADR-001). A working
Tableau→Power BI engine lives in `t2pbi` with 115 passing tests:

| Capability | Where |
|---|---|
| Tableau `.twb`/`.twbx` parsing | `core/extract.py`, `core/parse/` |
| Canonical model | `ir/model.py` |
| Tableau calc → DAX, with grain classification | `core/dax/` |
| Power BI PBIP generation (TMDL + PBIR) | `core/emit/` |
| Conversion flags, audit timeline | `ir/model.py`, `events.py` |
| Local-only AI assist | `assist.py` |
| Migration report | `report.py` |

Half the direction matrix does **not** exist: Power BI read (0 modules) and
Tableau write (0 modules). See ADR-005 — Phase 6 is two phases, not one.

---

## Core principle

### AI is an optional capability, never a system dependency

The application is fully functional with no model configured:

```
Mode A — No AI      parser → rules → converter → validator
Mode B — Local AI   … → unsupported item → Ollama → proposal → human → converter
Mode C — Remote     … → unsupported item → OpenAI-compatible → proposal → human → converter
```

In every mode the model **proposes**; a person applies (ADR-007).

### Deterministic first

```
deterministic rule → known mapping → transformation engine → validation
                                                 ↓ only if all fail
                                                AI
```

`SUM([Sales])` → `SUM(Sales[Sales])` needs no model, and reaching for one is a
defect.

---

## The three-layer story

```
                 DASHBOARDBRIDGE AI
                         │
       ┌─────────────────┼─────────────────┐
       ▼                 ▼                 ▼
  UNDERSTAND         TRANSFORM           VERIFY
   Metadata          Rules + AI         Validation
       └─────────────────┼─────────────────┘
                         ▼
                 TRUSTED MIGRATION
```

---

## Architecture

```
Browser → Next.js → FastAPI ─┬─ Artifact service
                             ├─ Metadata service
                             └─ Conversion orchestrator
                                    ├─ Rule engine  (deterministic)
                                    └─ AI router    (Ollama | OpenAI-compatible | none)
                                            ↓
                                    Validation engine
                                            ↓
                                    Report + audit
```

Everything crosses the **canonical model**. Adapters never know about each other:

```
Tableau ──▶ Canonical ──▶ Power BI
Power BI ──▶ Canonical ──▶ Tableau
```

Adding Qlik means one adapter, not a new converter per pair.

---

## Conversion classification

Three independent axes (ADR-004 — the original §21 conflated them):

```
ConversionMethod   deterministic | rule | ai_assisted | manual
ConversionStatus   converted | partial | ai_required | unsupported | failed
Severity           info | warning | manual
```

An item can be `ai_required` and end `manual` because the user declined AI. One
enum cannot express that, and §62 requires the audit trail to answer "what did
the AI actually do".

---

## Validation

Three categories ship: **Structural**, **Semantic**, **Visual**.

**Numerical validation does not ship** and is never implied (ADR-003). Comparing
source and target results requires executing both dashboards against live data —
two engines and warehouse credentials we do not have, and cannot have in Local
mode. Printing an unmeasured number would violate the principle below.

### No Hallucination Principle

The system never reports "100% successfully converted" unless validation proves
it. Vocabulary: `Verified` · `Partially verified` · `Unverified` · `Failed`.
Always state the denominator.

---

## Security

Uploaded artifacts are **untrusted input** and are never executed. Required:
extension and MIME validation, size limits, filename sanitisation, isolated
temporary storage, archive-bomb and decompression limits, parser sandboxing,
timeouts, and a malware-scan hook.

The LLM is an **untrusted transformation advisor**. It cannot execute code, reach
the filesystem or database, call arbitrary URLs, or change configuration. It
returns structured proposals, schema- and rule-validated before a human sees them.

Artifact content may contain hostile strings. Prompts separate `SYSTEM
INSTRUCTIONS` / `REFERENCE DATA` / `USER DATA`; workbook content is always data,
never instruction.

API keys live server-side, encrypted, behind a secret-provider abstraction. Never
in the browser, logs, reports, or telemetry.

### Privacy modes

`STANDARD` · `LOCAL_ONLY` · `ENTERPRISE_PRIVATE`. In `LOCAL_ONLY` there are no
outbound connections at all, and this is proven by an egress test, not asserted.

---

## Design language

Dark-first, subtle gradients, glass panels, fine borders, strong typography,
micro-interactions, data-rich cards, minimal clutter. **Framer Motion** is the
animation framework. Three.js only where a real visualisation benefit exists —
not decoration.

Progress is never faked: the UI renders real backend job events over SSE (§32,
§33).

The user must always know: *Where am I? What is happening? Why? What next? What
needs my attention?*

---

## Acceptance — the first vertical slice

The end-to-end architecture must work before breadth is added:

```
open app → choose Tableau → Power BI → upload → analyse → inventory
   → convert → validate → results
```

Even if conversion covers a small subset, every stage must be real. Demonstrated,
not asserted.
