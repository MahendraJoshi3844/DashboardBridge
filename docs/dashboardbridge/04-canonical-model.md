# Canonical BI Model

The seam of the whole system. Every adapter reads *into* it and writes *out of*
it, so no platform ever knows about another:

```
Tableau ──▶ Canonical ──▶ Power BI
Power BI ──▶ Canonical ──▶ Tableau
Qlik    ──▶ Canonical ──▶ …
```

Adding a platform means one adapter, not N² converters.

Derived from `t2pbi/ir/model.py`, which is proven against a real 1.1 MB
Superstore workbook — see ADR-002. Where this document and the code disagree, the
code is the source of truth until the migration in Phase 2 lands.

---

## Design rules

1. **Platform-neutral names only.** No `twb`, `pbix`, `shelf`, `TMDL` in a field
   name. If a concept exists in one platform only, it belongs in that adapter.
2. **Nothing is dropped silently.** Anything the model cannot represent produces
   a `ConversionFlag`. This is the product's central promise (§63).
3. **Stable identity.** Every object carries an `id` derived from its name path,
   never random, so re-running a conversion produces identical output.
4. **The model is data, not behaviour.** Dataclasses/Pydantic models with no
   conversion logic. Logic lives in engines.

---

## Entities

```
Project
└── Artifact                     the uploaded file, never executed
    └── CanonicalModel
        ├── DataSource[]
        │   └── Table[]
        │       └── Column[]     physical, calculated, or measure
        ├── Relationship[]
        ├── Parameter[]
        ├── Calculation[]        expressions, before translation
        ├── Visual[]
        ├── Dashboard[]
        └── ConversionFlag[]
```

### CanonicalModel

| Field | Type | Notes |
|---|---|---|
| `source_platform` | `Platform` | `tableau` \| `powerbi` \| … |
| `source_version` | `str` | as declared by the artifact; `""` when absent |
| `name` | `str` | |
| `datasources` | `DataSource[]` | |
| `relationships` | `Relationship[]` | model-level, not per-table |
| `parameters` | `Parameter[]` | |
| `visuals` | `Visual[]` | |
| `dashboards` | `Dashboard[]` | |
| `flags` | `ConversionFlag[]` | |

### Column

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | `"<table>.<name>"` |
| `name` | `str` | internal name |
| `caption` | `str \| None` | display name; often differs, carry both |
| `datatype` | `DataType` | canonical, not platform |
| `role` | `dimension \| measure` | |
| `grain` | `row \| aggregate \| None` | see below |
| `expression` | `Expression \| None` | set when calculated |

**`grain` is the field that matters most.** Tableau decides aggregation at the
shelf, at query time; Power BI must commit at definition time. `row` becomes a
calculated column, `aggregate` becomes a measure, and `None` means the grain
could not be determined and the item is refused rather than guessed. The rule is
implemented in `core/dax/grain.py` and is platform-neutral, so it belongs here.

### Expression

| Field | Type | Notes |
|---|---|---|
| `source_language` | `str` | `tableau_calc`, `dax`, … |
| `source_text` | `str` | verbatim, **never** interpolated into a prompt as an instruction |
| `references` | `FieldRef[]` | resolved dependencies, for the graph |
| `translation` | `Translation \| None` | filled by the conversion engine |

### VisualBinding

Replaces the Tableau-shaped `Encoding`/`ShelfRef` (ADR-002).

| Field | Type | Notes |
|---|---|---|
| `role` | `category \| value \| series \| detail \| tooltip \| filter` | |
| `field` | `FieldRef \| None` | `None` when unresolvable |
| `aggregation` | `Aggregation \| None` | `sum`, `avg`, `count_distinct`, … |
| `date_part` | `DatePart \| None` | `year`, `quarter`, `month`, … |
| `resolvable` | `bool` | `False` ⇒ flagged, never bound to a guessed field |

`resolvable=False` is load-bearing. Tableau writes shelf fields as
`[ds].[sum:Sales:qk]`, and constructs like `:Measure Names` or `Multiple Values`
name no real column. Binding them to a guess is the bug that made every visual in
the original engine point at a column that did not exist.

### ConversionFlag

| Field | Type |
|---|---|
| `item` | `str` |
| `stage` | `Stage` |
| `method` | `ConversionMethod` |
| `status` | `ConversionStatus` |
| `severity` | `Severity` |
| `reason` | `str` |
| `ref` | `str` |

Three separate axes, per ADR-004:

```
ConversionMethod   deterministic | rule | ai_assisted | manual
ConversionStatus   converted | partial | ai_required | unsupported | failed
Severity           info | warning | manual
```

---

## Dependency graph

Objects are converted in dependency order (§31), because a measure cannot be
translated before the columns it references are known:

```
DataSource → Table → Column → Calculation → Measure → Visual → Dashboard
```

Two properties the existing engine already proves are necessary:

- **Grain classification runs to a fixpoint.** A calc's grain depends on the
  grain of the calcs it references, so one pass is not enough.
- **Refusal propagates.** If calc B is refused, any calc A referencing B must
  also be refused — otherwise A's output references a measure that was never
  emitted, and the model only fails when a human opens it.

---

## Serialisation

The canonical model crosses the API boundary, so it is defined as Pydantic
models in `packages/contracts` and generated into TypeScript types for the web
app. Per §45, no untyped dictionaries cross a service boundary.

`snake_case` on the wire, matching the existing `Timeline.to_dict()`.

---

## What the model deliberately does not hold

| Not held | Why |
|---|---|
| Row data | Schema only, ever. Extracts are never read (§15). |
| Credentials | Connection identity only; secrets live in the secret provider (§50). |
| Pixel layout | Positions are advisory; exact layout does not survive migration and pretending otherwise is a false promise. |
| Rendered results | Requires executing a dashboard — see ADR-003. |
