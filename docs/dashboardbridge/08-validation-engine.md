# Validation Engine

Decides what the product is allowed to claim. Every number here ends up in front
of someone making a migration decision, so a number that cannot be derived is a
number that is not printed.

---

## The rule this engine exists to protect

> The system never reports success it did not verify.

A file being produced is not evidence that it is correct. Vocabulary:

```
Verified · Partially verified · Unverified · Failed
```

Always with the denominator. "94%" is meaningless; "132 of 143 objects converted,
8 requiring review, 3 unsupported" is a fact.

---

## Categories

| Category | Measures | Decidable offline |
|---|---|---|
| **Structural** | tables, columns, relationships, visuals, dashboards present in target | yes |
| **Semantic** | expression equivalence where decidable; parameter and filter mapping | partly |
| **Visual** | visual type, field bindings, title | yes |
| **Numerical** | source result vs target result | **no** |

### Numerical validation does not ship

Comparing results means executing both dashboards against live data: a Tableau
engine, a Power BI engine, and warehouse credentials. We have none of the three,
and in `LOCAL_ONLY` mode we cannot have them (ADR-003).

Therefore:

- The overall score is computed **only** from measured categories.
- The API always returns `numerical: { "measured": false, "reason": "..." }`, so
  the absence is explicit rather than inferred.
- No UI surface displays a numerical figure.

Printing an unmeasured number would violate §63, which is the product's central
claim. This is not a scoping preference; it is a correctness requirement.

---

## Scoring

Deterministic, documented, reproducible. The same conversion scores identically
every run. **An LLM never influences a score** (§38).

```
category_score = passed_checks / applicable_checks
overall        = Σ(category_score × weight) / Σ(weight)   over measured categories only
```

Default weights — structural `0.4`, semantic `0.4`, visual `0.2` — because a
structurally broken model does not open at all, while a visual difference is
cosmetic and repairable.

The formula is returned with the score and rendered next to it. A score whose
derivation a reader cannot follow is decoration.

A category with zero applicable checks is **excluded**, not scored `1.0`. Scoring
an absent check as a pass is how validation quietly becomes theatre.

---

## Checks always run

1. **Count parity** — source objects vs target objects, per kind.
2. **Dangling references** — does any emitted expression name something never
   emitted?
3. **Refusal integrity** — is every unconverted object flagged? An object that is
   neither converted nor reported is the silent drop this product exists to
   prevent.
4. **Determinism** — convert twice, diff. Any difference is a bug.
5. **Format validity** — does the target satisfy its format's structural
   requirements? For PBIP that includes every semantic-model table carrying a
   partition, without which Power BI rejects the entire model.

---

## Rule results

```json
{ "rule_id": "CALCULATION_COUNT_MATCH", "status": "PASS",
  "source_count": 27, "target_count": 27 }
```

```json
{ "rule_id": "CALCULATION_SEMANTIC_MATCH", "status": "WARNING",
  "source": "IF [Revenue] > 100000 THEN \"High\" ELSE \"Low\" END",
  "target": "IF(Sales[Revenue] > 100000, \"High\", \"Low\")",
  "note": "Structurally equivalent; numeric behaviour not executed." }
```

`PASS` · `WARNING` · `FAIL` · `NOT_APPLICABLE`. `WARNING` never counts as a pass.

---

## Semantic equivalence, honestly

Expression equivalence is decidable for a useful subset — identical structure
after normalisation, known-equivalent function pairs, argument reordering with
matching semantics.

It is **not** decidable in general. Where it cannot be decided, the result is
`WARNING`, not `PASS`, and the report says the expression was translated by rule
but its runtime behaviour was not executed.

Overstating this is the most tempting failure available to this engine, because
`PASS` makes the score look better and nobody notices until production.

---

## Comparison explorer

The user-facing half of validation: source and target side by side, expression by
expression, with the method, the rule or proposal id, and the check result.

```
Tableau                              Power BI
sum([Profit])/sum([Sales])    ──▶    SUM('Orders'[Profit])/SUM('Orders'[Sales])
                                     method: deterministic · rule TABLEAU_SUM_TO_PBI_SUM
                                     structural PASS · semantic PASS
```

Unconverted items show the refusal reason in the same layout, because what did
not convert is as much a result as what did.

---

## Executive summary

One page, derived entirely from measured results:

```
Migration completed with 91% verified compatibility

Objects analysed          143
Converted                 132
Requiring review            8
Unsupported                 3

Deterministic             121
AI-assisted                11    (9 accepted, 2 still under review)

Numerical equivalence     not verified — requires executing both dashboards
```

Then key risks, in the source's vocabulary rather than the parser's:

```
⚠ 3 advanced table calculations have no Power BI equivalent and need rewriting
⚠ 2 custom visualisations have no direct equivalent
```
