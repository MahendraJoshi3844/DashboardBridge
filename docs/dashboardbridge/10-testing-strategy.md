# Testing Strategy

Tests are written **before** the code they cover. A test written afterwards
proves the code does what it does, not what it should — and it never watched the
bug it claims to prevent.

The existing engine has 115 tests and they are the only reason it can be
refactored at all.

---

## The lesson that shapes this document

`tests/fixtures/sample.twb` was hand-written with plain shelf names
(`[ds].[Sales]`). Real Tableau writes `[ds].[sum:Sales:qk]`. Because of that one
detail, **a completely broken visual layer passed 32 tests** — every visual bound
to a column named `sum:Sales:qk` that existed nowhere.

Two tests also *asserted* invalid DAX as correct, because they were written after
the code and inherited its assumptions.

> Synthetic fixtures test your understanding of a format. Only real files test
> the format.

---

## Levels

### Unit

Parsers, rules, grain classification, expression rewriting, mapping, validation
rules, AI schemas, provider abstraction.

Fast, no I/O, no network, no model. `MockProvider` covers every AI path.

### Integration

One per boundary crossed:

```
upload → validate → parse → canonical
canonical → rules → convert → artifact
artifact → validate → score → report
proposal → schema → rules → security → review
```

### End-to-end (Playwright)

The §81 vertical slice, driven through the browser:

```
choose direction → upload → analyse → inventory
   → configure AI → convert → validate → download
```

Plus: reduced-motion disables all animation; keyboard alone completes the flow;
an error renders a human message with technical detail behind a toggle.

---

## Golden fixtures

```
fixtures/
  tableau/
    basic_dashboard/          minimal, every element once
    calculations/             the supported function surface
    filters/  parameters/
    advanced_calculations/    table calcs and LODs — must be refused
    unsupported_features/     must fail cleanly, never partially
    hostile/                  prompt-injection strings in field names and formulas
  powerbi/
    basic_dashboard/  measures/  relationships/  complex_model/
```

Every release runs all of them. `hostile/` is not optional: it is how the
injection defence stays real rather than aspirational.

Fixtures come from real exported artifacts. Where one must be hand-written, it
carries a comment naming the real file it was derived from.

---

## Required test classes

| Class | Asserts |
|---|---|
| **Determinism** | convert twice, byte-identical output |
| **Refusal integrity** | every unconverted object is flagged; no silent drops |
| **Dangling references** | no emitted expression names something never emitted |
| **Format validity** | the target satisfies structural requirements (e.g. every table has a partition) |
| **No-guess** | ambiguous grain is refused, not resolved |
| **Injection** | hostile fixture content never changes model instruction; output stays schema-valid |
| **Egress** | `LOCAL_ONLY` makes zero outbound connections during a full conversion |
| **Contract** | generated TS types match the Pydantic models; drift fails the build |

Each maps to a claim the product makes. A claim without a test is marketing.

---

## Accuracy metrics (§62)

Tracked per release against the golden set:

```
structural accuracy    converted structures / source structures
calculation accuracy   correct calculations / total calculations
visual accuracy        correct visuals / total visuals
```

AI contribution tracked separately and never blended into the headline:

```
AI-assisted · AI accepted · AI rejected · AI awaiting review
```

Blending them would hide whether the deterministic engine is improving, which is
the number that actually matters.

---

## What tests may never do

- Assert current behaviour to make a failing test pass.
- Use a fixture written to match the parser rather than the format.
- Mock the thing under test.
- Skip the RED step. If it never failed, it never proved anything.
- Treat an absent check as a pass.

---

## CI

Every push: lint, typecheck (Python and TS), unit, integration, contract drift,
golden fixtures. E2E on pull requests. Determinism and egress tests in the
release pipeline.

A red build is not merged. There is no "fix it after".
