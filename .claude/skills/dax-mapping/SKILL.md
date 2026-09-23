---
name: dax-mapping
description: Reference table and rules for translating Tableau calculated-field expressions into Power BI DAX. Use when implementing or extending the DAX translator, adding supported functions, or deciding whether an expression can be safely converted.
---

# Tableau Calc → DAX Mapping

Implementation lives in `engines/t2pbi/core/dax/`: `functions.py` (the tables),
`translator.py` (the rewriting), `grain.py` (measure vs calculated column).

## The one rule

Translate **only if every node is supported**. Otherwise write **nothing** and
raise `ConversionFlag(severity=MANUAL)` naming the reason. There is no commented
placeholder — an unconverted calc is absent from the TMDL and present in the
report. **Never guess DAX.**

## Grain: measure or calculated column?

Decided first, in `grain.py`, before any translation. Tableau picks aggregation at
the shelf; Power BI must commit at definition time, and getting this wrong is the
single largest source of invalid DAX.

| Formula shape | Emitted as |
|---|---|
| every column ref inside an aggregation — `SUM([a])/SUM([b])` | **measure** |
| no aggregation, only column refs — `DATEDIFF('day',[a],[b])` | **calculated column** |
| only constants, parameters, or other measures | **measure** |
| an aggregation wrapping a measure — `MIN([Some Measure])` | **refuse** |
| a row-level column beside a parameter or measure — `[Sales]*(1+[Rate])` | **refuse** |

The last two are refusals because the aggregation Tableau would have applied is
not stated anywhere in the formula, so any choice is a guess. Classification runs
to a fixpoint: a calc's grain depends on the grain of the calcs it references.

## Supported constructs

Function names are data-driven in `functions.py::SUPPORTED_FUNCS`.

| Tableau | DAX | Notes |
|---|---|---|
| `SUM/MIN/MAX/COUNT` | same | `AVG`→`AVERAGE`, `COUNTD`→`DISTINCTCOUNT` |
| `MEDIAN/STDEV/VAR` | `MEDIAN`/`STDEV.S`/`VAR.S` | |
| `IF a THEN b ELSE c END` | `IF(a, b, c)` | nested IF supported |
| `IF/ELSEIF/.../ELSE END` | `SWITCH(TRUE(), ...)` | an ELSEIF chain |
| `CASE [x] WHEN v THEN r END` | `SWITCH([x], v, r, ...)` | |
| `IFNULL(a,b)` / `ZN(a)` | `COALESCE(a,b)` / `COALESCE(a,0)` | |
| `DATEDIFF('day',a,b)` | `DATEDIFF(a,b,DAY)` | argument order is reordered |
| `YEAR/MONTH/DAY`, `NOW/TODAY` | same | |
| `LEFT/RIGHT/MID/LEN/UPPER/LOWER/TRIM` | same | |
| `ISNULL` | `ISBLANK` | |
| `CONTAINS` | `CONTAINSSTRING` | same argument order |
| `+ - * /` | same | **not** rewritten to `DIVIDE` |
| `'single quoted'` | `"double quoted"` | DAX reads `'x'` as a table name |
| `[Parameters].[P]` | `[P Value]` | the what-if parameter's value measure |

## Refused — flag, never attempt

`functions.py::UNSUPPORTED_MARKERS`. Scanned with string literals and
`[field names]` masked, so a column called `[Fixed Cost]` is not mistaken for a
level-of-detail expression.

- Table calculations: `WINDOW_*`, `RUNNING_*`, `RANK*`, `INDEX(`, `LOOKUP(`,
  `FIRST(`, `LAST(`, `TOTAL(`
- LOD expressions: `FIXED`, `INCLUDE`, `EXCLUDE` — **all forms**, including the
  simple `{FIXED [k]: SUM([x])}`. Do not add a `CALCULATE`/`ALLEXCEPT` rewrite
  without also proving the filter context matches; it usually does not.
- `SCRIPT_*`, `RAWSQL`
- Any function absent from `SUPPORTED_FUNCS`

Parameters **are** supported: they become what-if tables plus a value measure
(`core/emit/params.py`) and references resolve to `[<Param> Value]`.

## String literals

Everything is literal-aware. `_mask()` in `translator.py` builds a same-length
copy with literals (and optionally bracketed names) blanked, so offsets still
index the real expression. Any new scan must use it, or `CONTAINS([N],"END")`
will terminate an `IF` block at the `END` inside the string.

## Safety nets

Two run after translation, and both discard the result rather than shipping it:

1. Residual-keyword check — `THEN|ELSEIF|ELSE|WHEN|CASE|END` surviving in
   emitted DAX means the control-flow rewrite failed.
2. `pipeline._refuse_dangling_references` — a calc whose DAX names a calc that was
   itself refused gets refused too, iteratively.

## Adding a supported construct

1. Add the row to `functions.py`.
2. Write the failing test first (`tests/test_dax.py`, `test_dax_context.py`,
   `test_dax_literals.py`, `test_grain.py`), watch it fail, then implement.
3. Confirm the grain classifier still agrees: run `driver.py smoke` and check no
   emitted measure wraps an aggregation around another measure.
4. Confirm determinism — same formula, same DAX, every run.
