# Architecture

How the system is put together and why. Product intent is in `01-product-spec.md`;
the seam everything crosses is `04-canonical-model.md`.

---

## Shape

```
Browser
   │  REST + SSE
   ▼
Next.js (apps/web)          typed client, no conversion logic ever
   │
   ▼
FastAPI (apps/api)          thin: validate, authorise, delegate, stream
   │
   ├── Artifact service     store, never execute
   ├── Metadata service     artifact → canonical model
   └── Conversion orchestrator
          ├── Rule engine   deterministic, data-driven, versioned
          └── AI router     only when rules cannot finish
                  ├── Ollama
                  ├── OpenAI-compatible
                  └── Mock
          ↓
       Validation engine    structural · semantic · visual
          ↓
       Report + audit
```

---

## The one load-bearing decision

**Everything crosses the canonical model.** No adapter knows another exists.

```
Tableau ──▶ Canonical ──▶ Power BI
Power BI ──▶ Canonical ──▶ Tableau
Qlik    ──▶ Canonical ──▶ …
```

N platforms need N adapters, not N² converters. Adding Qlik must not touch the
UI, the AI layer, validation, reporting, or project management (§67).

The cost is real: every concept must be expressed platform-neutrally, and some
fidelity is lost at the boundary. That cost is paid deliberately, because the
alternative — direct pairwise converters — is unmaintainable at three platforms
and impossible at six.

---

## Layers and what may depend on what

```
apps/web      → packages/contracts
apps/api      → packages/contracts, engines/*
apps/desktop  → engines/*                        (Local mode — ADR-006)
engines/*     → packages/canonical-model
packages/*    → nothing
```

Enforced, not merely documented:

- **The web app never contains conversion logic** (Rule 8). It renders state.
- **Engines never import FastAPI.** They are callable from a CLI, a desktop
  shell, or a test with no server running. This is what lets the desktop app be
  Local mode rather than a second implementation.
- **`packages/contracts` depends on nothing** and is generated into TypeScript,
  so a backend change that breaks the frontend fails at build time.

---

## Two shells, one engine

| Shell | Deployment | Privacy mode |
|---|---|---|
| `apps/web` + `apps/api` | server or container | `STANDARD` / `ENTERPRISE_PRIVATE` |
| `apps/desktop` (pywebview) | single machine | `LOCAL_ONLY` |

Local mode is not a reduced build. It is the same engine with no server, no
ports, and no egress — which is exactly what §51 describes and what the existing
desktop app already does.

---

## Request lifecycle

```
POST /projects                      → project row
POST /projects/{id}/artifacts       → validated, isolated, never executed
POST /projects/{id}/analysis        → job; parse → canonical → flags
GET  /projects/{id}/events          → SSE, real job events
POST /projects/{id}/conversion      → job; orchestrated per dependency graph
POST /projects/{id}/validation      → job; three measured categories
GET  /projects/{id}/artifact        → the produced target
```

Analysis, conversion and validation are **jobs**, not request-scoped work. A
conversion may take minutes and must survive a dropped connection.

---

## Jobs and events

Long work runs on Celery with Redis as broker. Every job emits typed events into
a stream the API relays over SSE.

The event spine already exists as `t2pbi/events.py` — `ConversionEvent` and
`Timeline`. It gives, from one recording:

- live progress (§32)
- the audit trail (§41)
- replay

**Progress is never synthetic.** A percentage is `completed / total` of real
items, or it is not shown. Faking it would be the same class of lie as an
unmeasured validation score.

---

## Storage

| What | Where |
|---|---|
| Projects, jobs, results | PostgreSQL |
| Job state, queue, cache | Redis |
| Artifacts | storage abstraction — local FS, S3-compatible, Azure Blob |
| Secrets | secret-provider abstraction — env, Key Vault, Secrets Manager, Vault |

Artifacts are never stored in the database and never served from a path derived
from a user-supplied filename.

**Row data is never stored, anywhere.** The system reads schema only; extracts
are never opened.

---

## Failure model

Every error carries a category (§46) and two messages: one for a person, one for
an engineer behind *View technical details*.

```
UPLOAD_ERROR · PARSER_ERROR · UNSUPPORTED_ARTIFACT · METADATA_ERROR
RULE_ERROR · AI_ERROR · CONVERSION_ERROR · VALIDATION_ERROR · SYSTEM_ERROR
```

A failed stage never silently produces partial output presented as complete. It
fails the job, keeps what it learned, and reports it.

---

## Extensibility

```python
class BIPlatformAdapter(Protocol):
    def detect(self, artifact: Artifact) -> bool: ...
    def parse(self, artifact: Artifact) -> ParsedArtifact: ...
    def normalize(self, parsed: ParsedArtifact) -> CanonicalModel: ...
    def generate(self, model: CanonicalModel) -> Artifact: ...
    def validate(self, artifact: Artifact) -> ValidationResult: ...
```

`detect` and `parse` are separate because detection must be cheap and safe on
untrusted input, while parsing is expensive and sandboxed.

An adapter may implement read only, write only, or both — which is the honest
model, since Tableau today is read-only and Power BI is write-only (ADR-005).

---

## Determinism

Same input, identical output, always. This is a correctness requirement, not a
nicety: it is what makes conversions reviewable and diffable.

- Ids derive from name paths. Never random, never timestamped.
- Collections are ordered explicitly before emission.
- The AI path is *outside* the deterministic guarantee, which is another reason
  a model proposal is never applied without a human.

Enforced by a test that converts twice and diffs.
