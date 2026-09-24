# Spec Document — Power BI → Tableau in the web application

> **Type:** Spec Document (the *Why* + *What*). Technology-agnostic by design.
> The *How* goes in a Technical Design Plan, written only after this spec is
> reviewed.
>
> **Status:** Draft — awaiting review · **Owner:** Mahendra Joshi ·
> **Last updated:** 2026-09-24 · **Branch:** `ui-enhancements`

---

## 1. Problem Statement

DashboardBridge is pitched as a migration tool that works **in both directions**
between Tableau and Power BI. In the web application only one direction works.
The **Power BI → Tableau** card is shown but disabled. It says there is "no
engine behind this card today" and cites ADR-005.

That statement is out of date. Since it was written:

- The Power BI project reader has been built and is tested (roadmap `P6a`). The
  service already accepts a zipped Power BI project and shows its inventory.
- DAX → Tableau calculation rules exist (`P6b.2`).
- A Tableau workbook writer exists (`P6b.1`, `P6b.3`–`P6b.5`), with golden
  output fixtures.

A buyer who clicks the second card sees the product decline to do something
it can in fact do. That undersells the product in the demo where it most needs
to show that it works both ways. Worse, it teaches the viewer that the
interface and the engine disagree, which undermines the trust contract.

The gap is the last mile: there is no conversion request for this direction,
and no results, report or download for a Tableau output. There is also a
**fidelity gap** that must be closed before the card can honestly be enabled.
Today the Tableau writer records what it could not carry across only as
comments inside the produced file. A person using the web application would
never see those refusals. Enabling the direction without surfacing them would
break the "nothing dropped silently" rule.

**Goal:** a person can choose Power BI → Tableau, open a Power BI project, see
what is in it and what will cross, convert it, and download a Tableau workbook.
Every refusal is listed with its reason, and the product claims nothing about
the result that it has not checked.

## 2. Functional Requirements

**FR1 — Direction is available.** The Power BI → Tableau card is selectable
and describes accurately what it produces and what it does not.

**FR2 — Open a Power BI project.** After choosing this direction, the person
is asked for a **zipped Power BI project folder**. Every prompt, label and
empty state in the flow names Power BI and a project, not "a Tableau
workbook".

**FR3 — Analyse.** The existing analysis step runs on the project and shows
its inventory (tables, columns, calculations, relationships, visuals, pages),
counted from what was read, never estimated. "Expected outcome" figures are
shown only if they come from the rules that will actually run. If a figure
cannot be computed before conversion, the screen says so instead of showing a
number.

**FR4 — Convert.** Converting produces a Tableau workbook (`.twb`) using only
deterministic rules. The Tableau → Power BI direction behaves exactly as it
does today.

**FR5 — Every refusal is reported.** Anything that is not carried across, or
is carried across only in part, produces a flag with the object's name, what
happened to it, and the reason in plain words. Examples: a measure whose DAX
has no safe Tableau equivalent, a cross-table reference, a visual spanning
unrelated tables, a visual type with no mapping. These flags use the same
three-part classification as the other direction (method, status, severity).
They appear in:
- "What needs your attention", ordered by what the person must do.
- The side-by-side view, showing the DAX source beside the Tableau formula, or
  beside the reason it was refused.
- The migration report.

**FR6 — The counts add up.** The results headline gives converted / partial /
unsupported / failed counts over a stated total, and the parts sum to the
whole. Every flag in FR5 is accounted for in those counts.

**FR7 — Download.** The person can download the produced workbook. The file
name and every label say it is a Tableau workbook.

**FR8 — Honest verification status.** The results page shows one of
*Verified · Partially verified · Unverified · Failed*. Until a check exists
that reads the produced workbook back independently of the writer, the status
is **Unverified**, and the page says why in one sentence. It never shows a
check result that was not run.

**FR9 — Migration report.** The report is available for this direction. It
has the same sections as the other direction, with the source and target
named correctly throughout.

**FR10 — Switching direction.** Going back and choosing the other direction
clears the previous file, analysis and results. A Tableau file cannot be
carried into the Power BI flow, or the other way round.

## 3. Input / Output Behaviour (Contract)

| | |
|---|---|
| **Input** | A `.zip` of a Power BI project folder. It must contain a report and/or semantic model definition in text form (the PBIP format). |
| **Refused inputs** | `.pbix`, which is out of scope (ADR-005). A bare `.pbip` manifest without its folders. A Tableau file uploaded in this direction. Any archive that fails the existing size or decompression limits. |
| **Output** | One Tableau workbook (`.twb`), deterministic: the same project always produces byte-identical output. |
| **Also produced** | The flag list (FR5), the counts (FR6), the verification status (FR8) and the migration report (FR9). |
| **Not produced** | Data, extracts or a packaged `.twbx`. The workbook carries the schema and the connection shape only, as the other direction does. |

## 4. Constraints

- **Fidelity over guesswork.** A DAX expression is translated only when a rule
  translates it completely. Otherwise nothing is written for it and a flag is
  raised. No placeholder formula, no best-effort translation, and no
  automatic AI output in this direction.
- **Nothing dropped silently.** Every refusal the writer makes today, including
  the ones currently written only as file comments, must reach the flag list.
- **No unverified claims.** No wording, number or badge may imply the
  workbook was checked, opened in Tableau, or is numerically equivalent to the
  source (ADR-003).
- **Performance.** A typical project (≈5 tables, 60 columns, 25 measures,
  20 visuals) converts in under 30 seconds on a local machine. Analysis stays
  under 10 seconds.
- **Determinism.** Output and flag order are identical across runs and across
  processes.
- **Offline.** No new network access. In `LOCAL_ONLY` mode the existing egress
  test must still record zero outbound connections for a full run in this
  direction.
- **Parity of trust UI.** Anything the Tableau → Power BI results page shows
  about refusals, ordering and verification also appears for this direction.
- **Licensing.** Conversion is gated by the same licence check as the other
  direction.
- **Accessibility.** The existing standard applies: keyboard-only
  completion, visible focus, contrast of at least 4.5:1, and reduced motion.

## 5. Edge Cases & Error Handling

| Case | Handling |
|---|---|
| `.pbix` uploaded | Refused before upload completes, with the remedy: "Save as a Power BI project (PBIP) in Power BI Desktop, then zip the folder." |
| Bare `.pbip` manifest uploaded | Refused with the existing message telling the person to zip the whole folder. |
| Tableau file uploaded in this direction | Refused with a message that names the mismatch and offers to switch direction. Nothing is sent. |
| Zip containing no project | Refused as not a Power BI project, naming what was expected inside. |
| Project with a semantic model but no report | Converts the model. No worksheets are produced, and this is stated as a fact, not as a refusal. |
| Project with a report but no semantic model | Refused. Visuals cannot be bound without the model, and the message says so. |
| Measure whose DAX uses an unmapped function | Not written. Flag: "held for you", with the function named. |
| Measure referencing another table | Not written. Flag with the cross-table reason (ADR-005). |
| Visual using fields from two unrelated tables | Worksheet not bound. Flag naming both tables. |
| Visual type with no Tableau mapping | Flagged as unsupported, with the type named. |
| Measure with no data type in the source | Carried across with the documented default type. Flag at *info* severity stating the assumption. |
| Name collisions after flattening related tables | Resolved by the documented `Name (Table)` rule. Recorded as an info flag, so the rename is visible. |
| Hostile text in names or expressions | Treated as data. Escaped in the output and shown safely in the UI (existing prompt-injection fixtures). |
| Conversion fails part-way | No download is offered. The error is shown in plain words, the upload is unchanged, and retry resumes from analysis. |
| Licence expired | Conversion refused with the licence message. Past projects stay readable. |
| Person switches direction mid-flow | Previous state cleared (FR10). |

## 6. Acceptance Criteria

Each item is *demonstrated* (test or recorded run), not asserted.

- [ ] AC1 — On the landing page the Power BI → Tableau card is selectable, and
      its copy no longer says the engine is missing.
- [ ] AC2 — Using the zipped fixture project, a person completes
      *choose → open → analyse → convert → results → download* with the
      keyboard only. The downloaded file is a `.twb`.
- [ ] AC3 — Every "not carried" comment the writer puts in the produced
      workbook has a matching flag on the results page and in the report.
      This is shown by a test that counts both on the golden fixture and
      fails if they differ.
- [ ] AC4 — The results headline counts sum to the stated total, and the
      total includes every flagged object.
- [ ] AC5 — The results page shows **Unverified** with its reason, and shows
      no check results for this direction.
- [ ] AC6 — The side-by-side view shows at least one translated measure
      (DAX → Tableau formula) and at least one refused measure with its
      reason, using the golden fixture.
- [ ] AC7 — The same project converted in separate processes produces
      byte-identical workbooks and an identical flag list.
- [ ] AC8 — A typical-size project converts in under 30 seconds and analyses
      in under 10 seconds.
- [ ] AC9 — In `LOCAL_ONLY` mode the egress test records zero connections for
      a full run in this direction.
- [ ] AC10 — Every case in §5 has a test, or is shown in a recorded
      run, with the stated message.
- [ ] AC11 — The existing Tableau → Power BI tests all still pass, unchanged.
- [ ] AC12 — Screenshots of every screen in both directions, in light and
      dark mode, show no copy that names the wrong platform.

## 7. Open Questions

1. **Verification for this direction — in scope or later?** FR8 settles for an
   honest *Unverified*. Building a structural check that reads the `.twb`
   back independently would let the page say *Partially verified*. That adds
   a fair amount of work, so the proposal is to make it a follow-up spec.
2. **"Expected outcome" before conversion.** For Tableau sources this comes
   from flags raised while reading. For Power BI sources, most refusals
   happen only when the workbook is written. Should analysis run the DAX →
   Tableau rules as a dry run, so the prediction is real? Or should it show
   inventory only and say the prediction is not available for this direction?
3. **AI proposals for held DAX.** The review-and-apply flow exists for
   Tableau → DAX. Should held DAX → Tableau items offer it too? The proposal
   is **not in this spec**: this direction ships deterministic-only.
4. **Packaged output.** Is a plain `.twb` enough, or do buyers expect `.twbx`?
   A plain `.twb` is proposed, because there is no data to package.
5. **Tableau Desktop evidence.** No generated `.twb` has ever been opened in
   Tableau Desktop. Should enabling the card in a *customer* build wait for
   that manual check? Or is it acceptable in the demo build, with the
   caveat shown on the results page (as the Power BI direction does today)?
