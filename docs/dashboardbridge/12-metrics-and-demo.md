# 12 — Metrics (§54) and the demo scenario (§76)

**Status: draft, awaiting ratification.** The roadmap cites `§54` for `P7.7` and
`§76` for `P8.1`, and **neither section is in this repository**. Rather than
build against a citation nobody can read, this file states what those two
sections would have to say for the work to be done, in enough detail to argue
with. Ratify it, amend it, or replace it with the original if it turns up — but
`P7.7` and `P8.1` stay blocked while their specification is a reference to a
document that does not exist.

Everything below is derived from decisions already made and written down
elsewhere in `docs/dashboardbridge/`, not invented: the offline guarantee
(`09-security-spec`), the verdict vocabulary (`§63`), the honest denominator
(`02-architecture § Determinism`), and the AI audit trail (`07-ai-engine`).

---

## §54 — Metrics

### The constraint that shapes all of it

**No metric leaves the machine.** The product runs in the customer's
environment, often air-gapped, and `PRIVACY_MODE=local_only` is the default. A
metrics design that assumes a collector the vendor can read is a design this
product cannot have — so every number below is *for the operator and the user in
front of it*, exposed locally and never sent anywhere.

That is not a limitation to work around. It is the reason to be careful about
which numbers exist at all: nobody is aggregating them for us, so a metric that
does not change a decision on the machine it lives on has no reason to be
collected.

### What is measured, and what each one is for

**1. Conversion coverage — the number the product is judged on.**

Objects converted over objects *found*, never over objects attempted. The
denominator is the honest one established when shelf placements started being
read: Superstore moved from a flattering 44/177 to 103/267 because colour, size,
text and tooltip placements had been invisible rather than absent. A coverage
number whose denominator quietly excludes what the converter cannot see is the
single most misleading number this product could publish.

Reported per object kind — tables, columns, calculations, visuals, filters,
relationships, parameters — because one aggregate hides which part of a
migration is actually hard.

**2. Manual work outstanding.** The count of `MANUAL` flags, which is the
consultant's actual to-do list. Reported *beside* coverage rather than derived
from it: they are not complements. A filter that removes nothing is neither
converted nor manual work, and the day those two stop summing to the total is
the day the report is telling the truth about a third category.

**3. Method breakdown.** Deterministic, AI-assisted, and refused. `§62` requires
AI contribution to stay separable after the fact, and a single "converted"
number that mixes a rule-pack translation with an accepted model proposal makes
the product's central claim — deterministic engineering at its core —
unverifiable by its own output.

**4. Verdict distribution.** How many conversions ended `verified`,
`partially_verified`, `unverified`, `failed`. Never a "success rate": the
vocabulary exists precisely because success is not a thing this product claims,
and a metric that reintroduces the word undoes the decision.

**5. Duration, per stage.** The pipeline's six stages, separately. The target is
under 30 seconds for a typical workbook, and an aggregate cannot tell a slow
parse from a slow emit.

**6. Refusal reasons, counted.** Which rules fire most: unmapped DAX functions,
unbindable shelf fields, unreadable filter shapes. **This is the roadmap.** The
most common refusal is the next feature, and without counting them the backlog
is a matter of whoever complained most recently.

### What is deliberately not measured

* **Anything derived from a cell.** The product reads schema and never rows, so
  no metric may be computed from data — that would require reading it.
* **Workbook names, field names, customer identity.** A count is a count. A
  metric carrying the name of a customer's dashboard is workbook content, and
  the offline guarantee is about content rather than about volume.
* **Per-user productivity.** Accounts exist so that "whose conversion was this"
  has an answer (`P7.1`), not so that people can be ranked by throughput. A
  migration tool that reports who converted least becomes a tool people avoid
  using honestly, and the flags are the first thing they will stop reading.

### How it is exposed

Two surfaces, and the split matters:

* **Per conversion** — already in the migration report, and this is where a user
  meets these numbers. `P7.7` adds nothing here; it makes what is already
  reported also *countable*.
* **Per deployment** — a local endpoint (`GET /api/v1/metrics`) returning the
  aggregates above for this installation, plus process health. Readable by any
  signed-in user, because on a shared on-premise deployment these are the team's
  own numbers.

Prometheus text format is the obvious wire format and is **not** proposed here:
adopting it implies a scrape target, and a scrape target implies infrastructure
an air-gapped customer may not have. JSON first; the exposition format is a
question to answer when someone actually has a collector.

### Acceptance for `P7.7`

1. Every number above is produced by the deployment and readable from it.
2. A test asserts the coverage denominator counts objects **found**, and fails
   if anything the converter cannot handle is excluded from it.
3. A test asserts no metric field can carry a name from a workbook.
4. The egress acceptance test (`P7.8`) still passes with metrics enabled — the
   proof that nothing is phoning home is that nothing connects.

---

## §76 — The scripted demo scenario

### What it is for

Not a feature list. The one thing a BI consultancy needs to believe before
buying is that **the report tells the truth about what did not convert**, and
the only way to demonstrate that is to show something failing on purpose and
being reported accurately. A demo that only shows successes is indistinguishable
from every other converter's demo, and every one of those has burned the person
watching.

### The workbook

A **real** one, not the generated corpus. `P8.2`'s corpus is deliberately
synthetic — it exists to test size and shape — and a synthetic workbook makes
the demo a demonstration of the test fixture. Requirements:

* 15+ worksheets across 2+ dashboards
* 20+ calculated fields, including several that will not translate
* more than one data source, with a relationship between two of them
* filters that restrict, filters that do not, and at least one `except`
* a level-of-detail expression and a table calculation — the two families that
  most reliably refuse

Tableau Public is where such a workbook comes from, choosing one whose author
permitted downloads.

### The script

Seven steps, each with the sentence that makes it land.

1. **Show the Tableau workbook first.** Thirty seconds in the source tool. The
   audience has to see that this is a real dashboard someone built, not a
   fixture.
2. **Upload it. Say what leaves the machine: nothing.** The privacy mode is on
   screen already; point at it. For an on-premise buyer this is often the whole
   decision.
3. **Analysis: the inventory.** How many objects, of what kinds. This is the
   honest denominator, and saying so out loud is the moment to explain why it is
   bigger than a competitor's.
4. **Convert.** Under thirty seconds. Do not narrate the progress bar.
5. **Open the report at the refusals, not at the successes.** Pick the
   untranslatable calculation and read its stated reason aloud. *"It did not
   guess. It could have written something plausible here and it refused."*
   This is the demo.
6. **Open the generated project in Power BI Desktop.** It opens; the model
   loads; the pages are there. Then read the warning about incomplete data
   honestly: schema converts, rows do not, and the report says where the data
   was so the connection can be repointed.
7. **Show the mirror direction converting one thing back.** Briefly. It
   establishes that the canonical model is real rather than a diagram.

### What the demo must never do

* **Hide a refusal.** If the workbook chosen refuses something awkward on stage,
  that is the demo working. Choosing a workbook that refuses nothing would make
  step 5 impossible.
* **Claim a percentage without its denominator.** "80% converted" invites the
  next question and there is a good answer; giving the number without it invites
  the assumption that the denominator is flattering.
* **Run against a warmed cache or a pre-converted project.** The conversion is
  deterministic, so it can be rehearsed exactly — which removes any excuse for
  faking it.

### Acceptance for `P8.1`

1. The workbook is checked in (or its provenance recorded, if licensing forbids)
   and its size and shape meet the list above.
2. The scenario runs end to end from a clean deployment in under five minutes.
3. It is *scripted* — a runnable script, not a document someone follows — so
   that a failed demo is a failed test run beforehand rather than a surprise.
4. The generated project opens in Power BI Desktop. Until that is true on the
   demo workbook, `P8.1` is not done however well the script reads.

---

## Open questions for ratification

1. **Metrics endpoint or file?** An endpoint is easier to consume; a file
   survives the application being down, which is when an operator most wants it.
2. **Retention.** Per-deployment aggregates over what window — for ever, or a
   rolling period? For ever is simplest and grows without bound.
3. **Is the demo workbook redistributable?** If not, `P8.1`'s fixture is a
   pointer plus instructions rather than a file, and the acceptance test skips
   when it is absent — the same shape as the Superstore tests today.
