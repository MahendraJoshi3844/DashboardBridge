# Architecture Decisions

Decisions that change the master specification. Each states what the spec says,
what we are doing instead, and why. A coding agent follows these over the spec
where they conflict.

Status values: **ratified** (act on it) · **proposed** (needs the product owner).

---

## ADR-001 — This is a re-platforming, not a greenfield build

**Status:** ratified

The spec (§80) says *"Do not start by implementing Tableau parsing."* That is
right for a greenfield project and wrong here: a working Tableau→Power BI engine
already exists in `t2pbi` with 115 passing tests.

What exists, mapped to the spec:

| Spec | Exists today |
|---|---|
| Canonical BI Model §19 | `t2pbi/ir/model.py` |
| Rule engine §22 | `core/dax/functions.py`, `core/dax/grain.py` |
| Conversion classification §21 | `ir.Severity` + `ConversionFlag` |
| Audit trail §41 | `t2pbi/events.py` — `Timeline` |
| Progress events §32, §33 | `EventSink` passed into `pipeline.run` |
| LLM provider §26 | `t2pbi/assist.py` (Ollama, loopback-only) |
| Local-only mode §51 | `assist.py` talks to `127.0.0.1` and nowhere else |
| Report §42 | `t2pbi/report.py` |

That engine encodes expensive, hard-won knowledge — Tableau's encoded shelf
references, federation object-graphs, the measure-vs-calculated-column grain
rule, literal-safe DAX rewriting. Rebuilding it to satisfy a sequencing
recommendation would destroy value.

**Revised sequence:** lift the engine into `engines/`, derive the canonical model
*from* the proven IR (ADR-002), then build the API and web UX around it.

---

## ADR-002 — The canonical model is derived from the IR, not invented

**Status:** ratified

The spec's §19 canonical model and the existing IR describe the same domain. The
IR is proven against a real 1.1 MB Superstore workbook; the spec's JSON sketch is
not. We generalise the IR rather than replace it.

Two changes are required, because parts of the IR are Tableau-shaped:

- `Encoding` and `ShelfRef` carry Tableau shelf semantics. They move behind the
  Tableau adapter and the canonical model gets a platform-neutral
  `VisualBinding` (role, field ref, aggregation, date part).
- `Column.kind` ("column" | "measure") is a Power BI concept leaking into the
  canonical layer. It stays, because *grain* is genuinely platform-neutral, but
  it is renamed `grain` to say what it means.

---

## ADR-003 — Numerical validation is out of scope, and must not be promised

**Status:** ratified — this one is a correctness issue, not a preference

Spec §37 lists a **Numerical** validation category: *"Source result vs Target
result."* Comparing results means **executing both dashboards against live data**.
That requires a Tableau engine, a Power BI engine, and credentialed access to the
underlying warehouse. We have none of the three, and in Local/air-gapped mode
(§51) we cannot have them.

Shipping a "Numerical: 100%" figure that was never computed would directly
violate §63 (No Hallucination Principle), which is the product's core claim.

**Decision:** validation ships three categories — Structural, Semantic,
Visual — and the report states plainly that numerical equivalence was **not
verified**. The overall score is computed from the three that were actually
measured. A future phase may add numerical validation behind a real data
connection; until then the UI never displays a numerical figure.

---

## ADR-004 — Method, status and severity are three axes, not one

**Status:** ratified

Spec §21 collapses `SUPPORTED / PARTIALLY_SUPPORTED / AI_REQUIRED / UNSUPPORTED /
FAILED` into one enum. Those values mix three independent questions, and the
existing engine already needs them separated:

| Axis | Values | Answers |
|---|---|---|
| `ConversionMethod` | `deterministic` `rule` `ai_assisted` `manual` | *How* was it converted? |
| `ConversionStatus` | `converted` `partial` `ai_required` `unsupported` `failed` | *What became of it?* |
| `Severity` | `info` `warning` `manual` | *How loudly does the report say so?* |

`AI_REQUIRED` is a status, not a method: an item can be `ai_required` and still
end up `manual` because the user declined AI. Conflating them makes the audit
trail unable to answer "what did the AI actually do", which §62 requires.

---

## ADR-005 — The two directions are not symmetric, and the roadmap must say so

**Status:** ratified

Spec §74 (Phase 6) implies Power BI→Tableau is mostly reuse. Measured against the
codebase:

| Capability | Modules today |
|---|---|
| Tableau **read** | 3 |
| Power BI **write** | 4 |
| Power BI **read** | **0** |
| Tableau **write** | **0** |

Half the matrix does not exist. Worse, the two missing halves are the harder
ones:

- **Power BI read** — PBIP is text (TMDL + JSON) and tractable. `.pbix` is a zip
  containing a compressed SSAS model, which needs a real library or AMO; it is
  not "parse some XML".
- **Tableau write** — generating valid `.twb` XML is a complete new emitter with
  no existing code and no golden fixtures.

**Decision:** Phase 6 splits into **6a — read PBIP** (not `.pbix`) and
**6b — write `.twb`**, each with its own fixtures and acceptance criteria.
`.pbix` ingestion is a separate, later decision.

---

## ADR-006 — The desktop app becomes Local/air-gapped mode

**Status:** proposed — needs the product owner

We now have two front ends: the existing pywebview desktop app, and the Next.js
web application the spec calls for. Maintaining both as separate products is
waste; deleting the desktop app throws away a working implementation of §51.

**Proposal:** one shared engine, two shells. The web app is the enterprise
product. The desktop app is *the* Local/air-gapped deployment — no server, no
ports, no network, which is precisely what §51 and §52 `LOCAL ONLY` describe.
Both call the same `engines/` code, so features land once.

Rejecting this means deciding which shell to retire.

---

## ADR-007 — AI proposes; only a person applies

**Status:** ratified

Consistent with §27, §48 and §64, and already how `assist.py` behaves. Stated
here because it is the rule most likely to be eroded under delivery pressure.

An LLM response is a **proposal**. It is schema-validated, rule-validated, shown
next to the source expression with its reason, and applied only on an explicit
human action. There is no confidence threshold at which a suggestion silently
becomes output — §65's `auto_accept: 0.95` is therefore **rejected**: it is an
auto-apply path, and the product's entire claim is that it does not guess.

`auto_accept` is reinterpreted as *"pre-select this option in the review UI"*,
never *"apply without asking"*.

---

## ADR-008 — The engine keeps its parse-time IR; an adapter maps it to the canonical contracts

**Status:** ratified

ADR-002 said to generalise the IR into the canonical model. Doing the work
revealed that these are two models with two different jobs, and conflating them
makes both worse:

| | `t2pbi.ir` | `dashboardbridge_contracts.canonical` |
|---|---|---|
| Job | working model while parsing | wire model across a boundary |
| Mutability | mutable — the parser fills it in passes | frozen — nobody edits a received model |
| Validation | none, for speed over 128 objects | strict, `extra="forbid"` |
| Shape | convenient for lxml traversal | convenient for JSON and TypeScript |

Forcing one type to serve both means either a frozen model the parser cannot
fill, or a mutable unvalidated model crossing the API. Neither is acceptable.

**Decision:** `BIPlatformAdapter.normalize()` is the seam. The engine keeps its
IR; the adapter maps IR → `CanonicalModel` at the boundary. ADR-002 still holds
in the sense that matters — the canonical model was *derived from* the proven IR
and inherits its hard-won shape.

### The physical move (P2.1) is deferred

55 files reference `t2pbi`: the PyInstaller spec, the run skill and its
driver, 21 test modules, the desktop shell, and the docs. Moving them is
mechanical churn with real breakage risk and no functional gain, because the
adapter already provides the architectural separation the layout was meant to
express.

`engines/` is created now for the **new** adapter layer. `t2pbi` remains the
conversion engine it wraps. The move happens when something actually needs it —
most likely when a second platform adapter lands and the packaging is revisited
anyway.

A layout that is documented but not yet true is worse than one that is honest
about where the code is, so AGENTS.md says where things actually live.

---

## ADR-009 — Conversion runs on the engine's pipeline; the canonical model is the observable projection

**Status:** ratified

The read path is `artifact → engine IR → canonical` (ADR-008). The write path
could mirror it as `canonical → engine IR → artifact`, but doing so today would
mean building a canonical→IR mapping whose only consumer is an emitter that
already accepts the IR directly.

The engine's pipeline is the conversion engine (ADR-001). It already performs
extract → parse → map → translate → generate → report, is covered by 115 tests,
and produces the PBIP output.

**Decision:** the conversion endpoint runs the engine pipeline over the stored
artifact. Its flags and counts are mapped into the canonical contracts by the
same mapping the read adapter uses, so what the API reports is expressed in
platform-neutral terms even though the transformation itself is not.

### What this costs, stated plainly

The canonical model is not *in* the write path. It is the observable projection
of it. That is acceptable while there is exactly one write target, and stops
being acceptable the moment there are two: at that point a canonical→target
mapping has a second consumer and earns its existence.

**Trigger for revisiting:** the first line of Phase 6b (`.twb` generation). Do
not build the canonical→IR mapping before then — a seam with one implementation
is a guess about the second one.

### What this does not license

The pipeline's own rules still hold. Nothing may be reported as converted that
the engine did not convert, and the refusals the engine raises must survive the
mapping into the contracts rather than being smoothed away into a count.

---

## ADR-010 — Each engine is a separate product; DashboardBridge is the shell

Customers buy Tableau, MicroStrategy and Qlik migration separately and in any
combination. An engine that shipped inside the shell could not be left out, and
one that imported the shell could not be sold without it.

**Decision:** each engine lives in its own repository and imports nothing from
this one: `t2pbi` (Tableau ↔ Power BI, including the desktop app of ADR-006),
`mstr2pbi`, `qlik2pbi`. This repository keeps the UI, API, contracts, licensing,
validation and the seams, and installs engines as optional extras pinned by
commit. Power BI → Tableau is part of the Tableau product: its writer lives here,
on the canonical contracts, but needs `t2pbi` and the `tableau` licence feature.

A migration path is available to a person only when its engine is installed,
the licence includes it, and an administrator granted it to them
(`engines/conversion/directions.py`; administrators need no grant).

**Consequences:** the suite runs with every engine and with none; tests that
drive a conversion say which engine they need. This supersedes ADR-008's
"`t2pbi` stays here": the engine kept its IR (that part of ADR-008 stands) and
moved out with it.

