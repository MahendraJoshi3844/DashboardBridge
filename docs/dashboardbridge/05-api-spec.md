# API Specification

`/api/v1`. Every payload is a Pydantic model in `packages/contracts`, generated
into TypeScript. No untyped dictionary crosses this boundary (§45).

---

## Conventions

- `snake_case` on the wire, matching the existing `Timeline.to_dict()`.
- Ids are UUIDv4 except canonical-model object ids, which are deterministic name
  paths (`"Orders.Profit Ratio"`) so they are stable across runs.
- Long work returns `202` with a job, never blocks the request.
- Errors always carry a category and two messages (see below).
- Versioned in the path. A breaking contract change means `/api/v2`.

---

## Projects

```http
POST /api/v1/projects
```

```json
{ "source_platform": "tableau", "target_platform": "powerbi", "name": "Sales migration" }
```

`201` → `Project`. Source and target must differ and both must be supported;
otherwise `400 UNSUPPORTED_ARTIFACT`.

```http
GET /api/v1/projects/{project_id}
GET /api/v1/projects?limit=&cursor=
```

---

## Artifacts

```http
POST /api/v1/projects/{project_id}/artifacts
Content-Type: multipart/form-data
```

Validated **before** anything is written: extension, MIME, size, filename
sanitisation, archive-bomb limits (§15). Stored in isolated storage under a
generated name — never the user's filename.

`201` → `Artifact { artifact_id, kind, filename, size_bytes, sha256, detected_platform }`

`kind` is `source` or `target`. `GET /projects/{id}/artifact` returns the
produced target, so the distinction has to exist in the contract rather than
being inferred from timing.

`detected_platform` comes from `adapter.detect()`, which must be cheap and safe.
A mismatch with the project's `source_platform` is `400`, not a silent coercion.

---

## Analysis

```http
POST /api/v1/projects/{project_id}/analysis
```

`202` → `Job { job_id, kind: "analysis", status: "queued" }`

Analysis, conversion and validation are three jobs against one project, so `kind`
is what makes a job row findable.

```http
GET /api/v1/projects/{project_id}/analysis
```

`200` → `Analysis`:

```json
{
  "analysis_id": "...",
  "status": "completed",
  "model": { "...": "CanonicalModel" },
  "inventory": {
    "datasources": 3, "tables": 5, "columns": 54,
    "calculations": 21, "visuals": 21, "parameters": 6,
    "relationships": 2, "dashboards": 6
  },
  "complexity": { "score": 0.40, "band": "moderate", "formula": "..." },
  "compatibility": {
    "converted": 0, "partial": 0, "ai_required": 6,
    "unsupported": 2, "total": 143
  },
  "flags": [ { "...": "ConversionFlag" } ]
}
```

`complexity.formula` is returned so the UI can show the derivation. A score
without it is decoration.

Bands: `low` below 0.33, `moderate` below 0.66, `high` at or above it. The real
Superstore workbook scores 0.40.

---

## Conversion

```http
POST /api/v1/projects/{project_id}/conversion
```

```json
{
  "ai_enabled": false,
  "provider": "none",
  "privacy_mode": "local_only"
}
```

```python
class ConversionRequest(BaseModel):
    ai_enabled: bool = False
    provider: Literal["none", "ollama", "openai_compatible"] = "none"
    privacy_mode: Literal["standard", "local_only", "enterprise_private"] = "standard"
```

`ai_enabled: true` with `provider: "none"` is `400` — the request is
contradictory and guessing an intent here would be exactly the wrong instinct.

`202` → `Job`.

```http
GET /api/v1/projects/{project_id}/conversion
```

`200` → `Conversion { conversion_id, status, compatibility, model, artifact_id, flags }`

`compatibility` counts by the three axes of ADR-004, so the caller can answer
both *what became of it* and *how was it done*.

`model` is the produced canonical model with `Column.translation` filled. The
comparison view puts each source expression beside its target, and without this
that column is empty for every row.

There is no `stages[]` field. Stage-by-stage progress belongs to the event
stream, not to this resource.

---

## Events (SSE)

```http
GET /api/v1/projects/{project_id}/events
Accept: text/event-stream
```

```
event: conversion.progress
data: {"stage":"calculation_translation","completed":18,"total":27}

event: conversion.item
data: {"kind":"calc","name":"Profit Ratio","outcome":"crossed","method":"deterministic"}

event: conversion.completed
data: {"conversion_id":"..."}
```

Events are relayed from the job's real `EventSink`. **No event is synthesised to
smooth a progress bar.** A client reconnecting receives the recorded timeline
from `last_event_id`, so a dropped connection loses nothing.

SSE for MVP; WebSockets only if bidirectional interaction becomes necessary
(§33).

---

## Validation

```http
POST /api/v1/projects/{project_id}/validation
GET  /api/v1/projects/{project_id}/validation
```

```json
{
  "overall": { "score": 0.91, "verdict": "partially_verified" },
  "categories": {
    "structural": { "score": 0.98, "checks": 42, "passed": 41 },
    "semantic":   { "score": 0.89, "checks": 27, "passed": 24 },
    "visual":     { "score": 0.94, "checks": 21, "passed": 20 }
  },
  "numerical": { "measured": false, "reason": "Requires executing both dashboards against live data." },
  "rules": [ { "rule_id": "CALCULATION_COUNT_MATCH", "status": "PASS", "source_count": 27, "target_count": 27 } ]
}
```

`numerical.measured` is **always `false`** in v1 and the field exists precisely so
the absence is explicit rather than inferred (ADR-003). `overall.score` is
computed only from measured categories.

---

## Artifact download

```http
GET /api/v1/projects/{project_id}/artifact
```

`200` with the produced file. `409` if conversion has not completed — a partial
artifact is never served as if it were finished.

---

## Report

```http
GET /api/v1/projects/{project_id}/report?format=json|html
```

PDF and CSV are later (§42).

---

## Settings

```http
GET  /api/v1/settings/providers
POST /api/v1/settings/providers
```

API keys are **write-only over this API**. A `GET` returns
`{"configured": true, "key": null}` — never the value, never a masked prefix that
leaks length. Keys are stored server-side through the secret provider and never
appear in logs, reports, telemetry, or a response body (§50).

---

## Errors

```json
{
  "category": "PARSER_ERROR",
  "message": "We could not read the workbook. It appears to use a Tableau feature this version does not support.",
  "detail": "lxml.etree.XMLSyntaxError: Opening and ending tag mismatch: worksheet line 4412",
  "request_id": "...",
  "project_id": "..."
}
```

`message` is for a person and never contains a stack trace, a path, or an HTTP
code. `detail` is for an engineer and is shown behind *View technical details*.
Both are always present; neither substitutes for the other (§46).
