# Conversion Engine

Turns a canonical model of the source into a canonical model of the target, then
into an artifact. Deterministic wherever possible; AI only where nothing else can
reach (§23).

---

## Order of attempt

```
deterministic rule → known mapping → transformation engine → validation
                                                 ↓ only when all have failed
                                                AI proposal → human → apply
```

`SUM([Sales])` → `SUM(Sales[Sales])` is a table lookup. Reaching for a model
because writing the rule is tedious is a defect, not a shortcut.

---

## Orchestrator

```
load canonical model
   ↓
build dependency graph
   ↓
classify grain to a fixpoint
   ↓
convert in dependency order
   ├── deterministic
   ├── ai_required   → proposal, never auto-applied
   └── unsupported   → flagged
   ↓
propagate refusals
   ↓
build target model
   ↓
generate artifact
   ↓
validate
   ↓
report
```

### Dependency order

```
DataSource → Table → Column → Calculation → Measure → Visual → Dashboard
```

A calculation cannot be translated before the columns it references are known,
and a visual cannot bind before its fields exist.

### Grain classification runs to a fixpoint

A calculation's grain depends on the grain of the calculations it references, so
a single pass is wrong. Iterate until no verdict changes.

| Formula shape | Grain |
|---|---|
| every column reference inside an aggregation | `aggregate` → measure |
| no aggregation, only column references | `row` → calculated column |
| only constants, parameters or measures | `aggregate` → measure |
| an aggregation wrapping a measure | **refuse** |
| a row-level column beside a parameter or measure | **refuse** |

The last two are refused because the aggregation the author intended is not
stated anywhere in the formula. Any choice would be a guess, and a guess that
looks plausible is the most damaging output this system can produce.

Implemented in `core/dax/grain.py`.

### Refusal propagates

If calculation B is refused, every calculation referencing B is refused too,
iteratively. Otherwise A's emitted expression names a measure that was never
written, and the model fails only when a human opens it — which is precisely the
surprise the product exists to prevent.

---

## Rule engine

Data-driven and versioned. Rules are YAML under `engines/rules/`, not Python
literals, so they can be reviewed, diffed, and eventually shipped as rule packs
(§68).

```yaml
rule_id: TABLEAU_SUM_TO_PBI_SUM
version: 1
source: { platform: tableau, function: SUM }
target: { platform: powerbi, function: SUM }
strategy: deterministic
confidence: 1.0
```

```
engines/rules/
  tableau/
    calculations/   function mappings, control flow, literals
    visuals/        mark class → visual type
    filters/
    parameters/
    datatypes/
```

Today these live in `core/dax/functions.py` as Python dicts. `P3.1` moves them.

### Refusal markers

Some constructs disqualify a whole expression: table calculations
(`WINDOW_*`, `RUNNING_*`, `INDEX`, `RANK`, `LOOKUP`), level-of-detail
expressions (`FIXED`, `INCLUDE`, `EXCLUDE`), `SCRIPT_*`, `RAWSQL`.

**All LOD forms are refused, including the simple ones.** A `FIXED` rewrite to
`CALCULATE`/`ALLEXCEPT` is only correct if the filter context matches, and it
usually does not. An earlier version of the reference documentation claimed this
mapping was safe; it is not, and following it would have shipped wrong DAX.

Marker scanning masks string literals and bracketed names, so a column named
`[Fixed Cost]` is not mistaken for an LOD expression.

---

## Expression rewriting

Everything is literal-aware. A length-preserving mask blanks string literals so
offsets still index the real expression, and every scan uses it. Without this,
`CONTAINS([Name], "END")` terminates an `IF` block at the `END` inside the
string.

Rewrites applied in order: single→double quotes (DAX reads `'x'` as a table
name), control flow to `IF`/`SWITCH`, argument reordering (`DATEDIFF`), null
helpers, function mapping, reference resolution.

References resolve to the name the target actually emits, which is often the
caption rather than the internal name — pointing at the internal name produces
DAX referencing something that does not exist.

---

## Safety nets

Both discard the result rather than shipping it:

1. **Residual keyword check** — a source control-flow keyword surviving into
   emitted output means the rewrite failed.
2. **Dangling reference check** — an expression naming an object that was never
   emitted is refused, iteratively.

---

## Classification recorded per object

Three axes (ADR-004), because one enum cannot express "the AI was asked, the user
declined, so a human must do it":

```
method    deterministic | rule | ai_assisted | manual
status    converted | partial | ai_required | unsupported | failed
severity  info | warning | manual
```

Every object gets all three, plus the rule id or proposal id that produced it.
That triple is what makes the audit trail able to answer §62's question: what did
the AI actually contribute?

---

## Target generation

The target adapter turns the target canonical model into an artifact. For Power
BI that is PBIP — TMDL semantic model plus PBIR report — implemented in
`core/emit/`.

Format knowledge stays inside the adapter. The orchestrator never knows what
TMDL is.

Structural requirements the generator must satisfy are the generator's
responsibility, and the validator checks them independently — for example, every
emitted semantic-model table carries a partition, without which Power BI rejects
the whole model.
