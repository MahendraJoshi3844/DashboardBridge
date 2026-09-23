# UX Specification

The interface must feel like a premium enterprise developer product, not an admin
dashboard. Screens and personas are in `01-product-spec.md`; this covers
behaviour, state, motion and accessibility.

---

## The five questions

At every moment the user must be able to answer:

> Where am I? · What is happening? · Why? · What next? · What needs my attention?

Any screen that fails one of these is unfinished.

---

## State machine

The frontend never coordinates ad-hoc booleans. One machine, one current state
(§58):

```
IDLE → SOURCE_SELECTED → UPLOADING → ANALYZING → ANALYSIS_READY
     → CONFIGURING → CONVERTING → VALIDATING → COMPLETED

ANY_STATE --error--> ERROR --retry--> origin
                     ERROR --cancel-> IDLE
```

Rules:

- Transitions are triggered by server events, never by a timer.
- `ERROR` retains the state it came from, so retry resumes rather than restarts.
- Illegal transitions throw in development and are logged in production.

**`retry` and `cancel` are events, not states.** There is no screen called
"RETRY". An earlier drawing of this diagram listed them alongside states, which
is a category error and would have produced two unreachable states.

**`CONFIGURING` is client-only.** It is a real screen — the AI-consent decision
of §24 — but it has no endpoint: the configuration it collects becomes the body
of `POST /conversion`. `05-api-spec.md` is therefore complete as written, and no
call should be invented to match this state.

---

## Progress is never faked

The analysis and conversion screens render **real events** from the job's stream
(§32, §33). A percentage is `completed / total` of real items or it is not shown.

When the backend has no measurable total, show an indeterminate indicator and the
current stage name — not a bar creeping toward 90%.

```
✓ File validated
✓ Tableau artifact detected
✓ Workbook parsed
✓ Data sources discovered
● Analysing calculations          18 / 27
○ Visualisations
○ Compatibility scan
```

A conversion may complete in under a second. That is not a reason to slow it
down: show the real elapsed time, and offer replay of the recorded event
timeline if the run is worth narrating.

---

## Design language

```
dark-first · subtle gradients · glass panels · fine borders
strong typography · micro-interactions · data-rich cards · minimal clutter
```

Avoid: neon, heavy particle effects, oversized animation, decorative 3D.

Data — expressions, names, counts — is set in a monospace face. It reads as
precise and auditable, which is the product's whole argument.

Colour carries meaning and nothing else:

| Role | Use |
|---|---|
| source ink | the source platform's objects |
| target ink | the target platform's objects |
| held ink | items requiring a human |
| status | good / warning / serious / critical, with icon **and** label |

Status is never colour alone. Any categorical palette is validated for
colour-vision deficiency before shipping, not eyeballed.

---

## Motion

**Framer Motion is the animation framework.** Three.js only where a real
visualisation benefit exists — a flow of converted objects qualifies; a spinning
logo does not.

| Where | What |
|---|---|
| Page transitions | fade + slide, 200–260 ms |
| Cards | opacity + scale, staggered |
| Counters | animate 0 → real value on arrival |
| Conversion | source → transform → target, driven by real events |
| Validation ring | animates to the measured score, never past it |

Motion communicates state change. Motion that communicates nothing is removed.

---

## Reduced motion

`prefers-reduced-motion: reduce` disables all animation, including
JavaScript-driven animation. A CSS media query alone does **not** stop a
JS animation library — the library's own reduced-motion configuration must be
set, or the setting is ignored where it matters most.

With motion off, every screen remains fully legible and every number is present.
Motion is never the only carrier of information.

---

## Accessibility

- Full keyboard operation; the whole flow completable without a mouse.
- Visible focus, never removed.
- Semantic landmarks and labels; live regions for job progress.
- Text contrast ≥ 4.5:1 against its own surface. Disabled controls are exempt;
  meaningful text is not.
- Errors announced, not merely coloured.

Contrast is measured, not judged by eye.

---

## Copy

Words are design material. Write from the user's side of the screen.

- Name things by what the user controls: *Open workbook*, not *Ingest artifact*.
- An action keeps its name through the flow: `Convert` produces `Converted`.
- Errors say what happened and what to do, in the interface's voice, and never
  apologise or show an HTTP code.
- Empty states are invitations: *"Drop a Tableau workbook to begin."*
- Held items say **"Held for you — the aggregation isn't stated in the formula"**,
  never *"Failed"*. They are the product working, not failing.

Each element does exactly one job. A label labels; an example demonstrates.

---

## Results

Lead with the verdict and its denominator:

```
132 of 143 objects converted · 8 need review · 3 unsupported
```

Never a bare "94%". Never "100% successfully converted" without validation
evidence.

The comparison explorer is the flagship: source and target side by side,
expression by expression, with method, rule id, and check result. Unconverted
items appear in the same layout with their reason — what did not convert is as
much a result as what did.

---

## Ordering by actionability

Lists of items requiring attention are ordered by **what a person must do**, not
by when the engine found them.

A calculation needing hand-written DAX outranks a field-well needing a click.
Timeline order once buried all six actionable calculations beneath forty
field-well notices, where nobody would ever see them.

**The three axes of ADR-004 are not sufficient to order this**, which we learned
by trying. Ranking on severity, then status, then method puts eleven
`unsupported` field wells above five `ai_required` calculations - the same
inversion, reached from the other direction. `status` answers *what became of
it*, not *what kind of work is it*.

The **stage** is what separates hand-written DAX (`translate`) from a field well
(`map`) from formatting (`generate`), so ordering is:

```
failed first, then by stage (translate > map > generate), then status, then method
```

An axis that answers a different question cannot be borrowed to answer this one.
