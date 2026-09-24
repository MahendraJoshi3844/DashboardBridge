# Technical Design — Power BI → Tableau in the web application

> Implements `docs/specs/SPEC-powerbi-to-tableau-web.md`. The spec says *what*;
> this says *how*. **Status:** approved to build 2026-09-24 · **Branch:**
> `ui-enhancements`

## Decisions carried in from spec review (2026-09-24)

| Open question | Decision |
|---|---|
| Q1 Read-back validation of the `.twb` | **Later, own spec.** Validation for this direction returns an honest *Unverified* with a stated reason. |
| Q2 Expected outcome before conversion | **Dry-run the rules.** Analysis of a Power BI source runs the real conversion into a throwaway directory, so the prediction and the result come from the same code. |
| Q3 AI proposals for held DAX | Out of scope. This direction is deterministic-only. |
| Q4 `.twb` or `.twbx` | Plain `.twb`: there is no data to package. |
| Q5 Release gate | **Enable, with caveat.** The results page says no generated workbook has been opened in Tableau Desktop. |

## 1. The fidelity gap, and how it closes

`engines/adapters/tableau_emit.write_twb` reports refusals only as
`<!-- not carried: … -->` comments, and it drops other things with no trace at
all:

| Silently dropped today | Now reported as |
|---|---|
| Model parameters (never written) | `unsupported`, one flag per parameter |
| Visual filters (never written) | `partial`, one flag per visual |
| Bindings in wells other than rows/columns, or unresolvable, or whose table is not in any data source | `partial`, one flag per visual, naming the fields |
| Visual type with no mark mapping (written as `Automatic`) | `partial`, naming the type |
| Dashboard layout (only a zone list is written) | `partial`, one per dashboard |
| Dashboard zone naming a visual id instead of the worksheet name (**bug**: `retail.twb` zone `v1`) | **Fixed**: zones use the worksheet name. A visual id that matches no worksheet is flagged. |

**Mechanism.** A new `emit_twb(model, out_dir) -> TwbEmission(path, flags)`
does the writing. Every commented refusal is built from the same record as its
flag, so the two cannot drift apart. `write_twb` becomes a thin wrapper that
returns the path, so existing callers and `TableauAdapter.generate` keep their
signatures. New flags that had no comment get **no** new comment, so golden
bytes change only where a defect is fixed.

## 2. Engine: `engines/conversion/to_tableau.py`

```
convert_powerbi_to_tableau(artifact: bytes, out_dir: Path, name: str) -> ConversionOutcome
```

1. `PowerBIAdapter().parse(bytes)` → `normalize` → canonical model (named `name`).
2. `emit_twb(model, out_dir)` → path + writer flags.
3. Flags = reader flags + writer flags, sorted by `(item, stage, reason)` for
   determinism.
4. **Compatibility per object**, not by subtraction. The objects are the
   tables, columns, relationships, parameters, visuals and dashboards in the
   model. Each object's status is its worst flag, and an object with no flag
   converted. The parts sum to the total by construction (AC4). Status rank:
   `failed > unsupported > ai_required > partial > converted`.
5. `Timeline` from an `EventSink`: one event per object (crossed or held). A
   calculated column carries `source` (DAX) and `result` (Tableau formula), so
   the replay and side-by-side views have what they need.

It reuses `ConversionOutcome` from `run.py`. There are no contract changes.

## 3. API (`apps/api`)

| Endpoint | Change |
|---|---|
| `POST …/analysis` | Power BI source: after reading, dry-run `convert_powerbi_to_tableau` in a temp dir. `compatibility` and `flags` come from that run. |
| `POST …/conversion` | Dispatch on `(source, target)`. Power BI → Tableau stores the `.twb` itself as the target artifact (`{name}.twb`, `detected_platform=tableau`). Any other pair is refused, as before. |
| `GET …/artifact` | Media type from the stored file name: `.zip` → `application/zip`, `.twb` → `application/xml`. |
| `POST …/validation` | Tableau target: a completed `Validation`, verdict `unverified`, no categories and no score, plus one rule `TABLEAU_READBACK` = `NOT_APPLICABLE` with the reason. No check is run, and none is claimed. |
| `GET …/report` | The subtitle names the project's real source and target platforms. |

## 4. Web (`apps/web`)

- `lib/direction/copy.ts` (new, unit-tested): every direction-dependent noun
  and sentence in one table. Components read from it, so no screen hard-codes
  a platform.
- `lib/upload/precheck.ts`: `precheck(file, source)`. Tableau accepts
  `.twb`/`.twbx`. Power BI accepts `.zip`, gives remedies for `.pbix`/`.pbit`
  and the `.pbip` manifest, and refuses the other platform's file with a
  "switch direction" message.
- `DirectionChoice`: the Power BI → Tableau card is `available`, with honest
  bullets.
- `Dropzone`, `UploadScreen`, `MetadataDashboard`, `ConvertScreen`,
  `ResultsScreen`, `ComparisonPanel`: wording comes from `copy.ts`. Results
  shows the Tableau Desktop caveat and a "Download the Tableau workbook"
  button.

## 5. Tests (written first)

| Test | Proves |
|---|---|
| `tests/dashboardbridge/test_tableau_writer_flags.py` | AC3 (every comment has a flag, counted on both goldens). Each silent drop in §1 now raises a flag. Zone names resolve to worksheets. |
| `tests/dashboardbridge/test_powerbi_to_tableau.py` | Engine: counts sum to total (AC4). Determinism across processes (AC7). A translated measure and a refused one (AC6). Performance on a generated project (AC8). |
| `tests/dashboardbridge/test_powerbi_conversion_api.py` | Upload → analyse (dry-run prediction equals result) → convert → download `.twb` → validation *Unverified* → report subtitle. Edge cases in §5 of the spec (AC10). |
| `test_local_only_egress.py` (extended) | AC9 |
| `apps/web/tests/direction-copy.test.ts`, `precheck.test.ts` (extended) | Copy never names the wrong platform. Per-direction upload rules. |
| Full existing suites | AC11 |

## 6. Tasks

- [ ] D1 Writer flags + zone fix (`emit_twb`), goldens regenerated and diff reviewed
- [ ] D2 `convert_powerbi_to_tableau` + per-object compatibility + timeline
- [ ] D3 API: conversion dispatch, download media type, validation stub, report subtitle
- [ ] D4 API: analysis dry-run for Power BI sources
- [ ] D5 Web: `copy.ts`, precheck per direction, enable card, screen wording
- [ ] D6 Egress + performance + determinism tests for this direction
- [ ] D7 Recorded end-to-end run with screenshots (AC2, AC12); roadmap/spec updated
