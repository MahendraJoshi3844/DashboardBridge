# Product Specification

What the product is for, who uses it, and what they must be able to do. No
implementation here — see `02-architecture.md`.

---

## Positioning

Not *"we convert Tableau to Power BI"*. That is a feature, and a commoditised one.

> **DashboardBridge AI is an explainable BI migration intelligence platform that
> analyses, maps, converts and validates BI dashboards — with deterministic
> engineering at its core and AI only where it adds value.**

The differentiator is **auditability**. A competitor can produce a file. The
claim here is that a migration architect can defend every transformation to a
sceptical stakeholder, and see precisely what did not come across.

---

## Personas and what each must be able to finish

| Persona | Their question | Must be able to |
|---|---|---|
| **BI developer** | "What do I have to rebuild by hand?" | See every unconverted item with its reason and source expression; copy generated DAX |
| **Data analyst** | "Does the output match the source?" | Compare source and target side by side without reading code |
| **Migration architect** | "How big is this programme?" | Get inventory, complexity, coverage and risk before committing |
| **Director** | "Can we do this, and what will it cost?" | One page: coverage, risk, effort remaining |

The developer and the architect are the buying centre; the director signs. The
UI must serve the director in under a minute without weakening what the
developer needs.

---

## The journey

```
Landing → Direction → Upload → Analyse → Inventory → Compatibility
   → AI decision → Convert → Validate → Results → Report
```

Each stage is observable. The user is never asked to wait on an opaque process,
and never receives output without an account of how it was produced.

---

## Screens

| Screen | Job | Key content |
|---|---|---|
| Landing | Choose direction | Two cards; motion on selection |
| Upload | Accept an artifact | Dropzone, client-side validation, size and type |
| Analysis | Show work happening | Real staged events, never faked |
| Inventory | Establish scale | Count cards, complexity, category breakdown |
| Compatibility | Set expectations | What converts, what will not, why |
| AI decision | Informed consent | Why AI is recommended, what it will see, opt out |
| Conversion | Show progress | Real stages from the job's event stream |
| Results | Deliver the verdict | Coverage, verified counts, download |
| Comparison | Prove it | Source ↔ target, expression by expression |
| Executive | Support a decision | Coverage, risk, effort |
| Settings | Configure | Provider, privacy mode, thresholds |

---

## Inventory — what must be extracted

Grouped as the user thinks about them, not as the parser finds them.

**Data** — data sources, tables, columns, data types, relationships, joins, unions

**Semantic** — dimensions, measures, calculated fields, parameters, hierarchies

**Visualisation** — dashboards, worksheets, visuals, visual types, filters, actions

**Logic** — calculations, aggregations, expressions, conditional logic, date logic

**Presentation** — colours, fonts, formatting, layout, tooltips

Anything found that cannot be represented produces a flag. Nothing is dropped
silently.

---

## Complexity score

Shown before conversion so the architect can scope work. Derived from counts
weighted by known conversion difficulty — calculated fields and custom visuals
weigh far more than columns.

The formula is published next to the number. An unexplained score is decoration.

---

## AI as informed consent

AI is never invoked silently. When deterministic rules cannot finish, the product
states what it found, what a model would be asked, and what it would see:

> The workbook contains 4 advanced table calculations with no deterministic Power
> BI equivalent. AI can draft these for review. **7 operations. Only the
> expression and its schema are sent — never the workbook.**
>
> `[ Use AI ]` `[ Continue without AI ]`

Continuing without AI is a first-class path, not a degraded one. Those items are
reported as requiring manual work, which is the truth.

---

## Success criteria

The product succeeds when a migration architect can hand the report to a
stakeholder and defend it without opening the tool. That means:

1. Every converted object traceable to the rule or proposal that produced it.
2. Every unconverted object explained in terms of the source, not the parser.
3. No number displayed that was not measured.
4. Identical input produces identical output, every run.

---

## Out of scope for v1

| Not building | Why |
|---|---|
| Remote connectors (Tableau Server, Power BI Service) | Local upload only; auth and tenancy are their own programme |
| Numerical result comparison | Requires executing both dashboards — ADR-003 |
| Pixel-accurate layout transfer | Does not survive migration; claiming it would be false |
| Multi-user collaboration | Single-operator tool first |
| `.pbix` ingestion | Compressed SSAS model, not text — ADR-005 |
