# Module Spec — DAX translator

**Code:** `t2pbi/core/dax/` (`functions.py`, `translator.py`)

## Purpose
Stage 4. Translate a Tableau calculated-field formula into DAX — **only if every
construct is supported**. Otherwise return no DAX and a reason (caller raises a
MANUAL flag). Never emit guessed DAX.

## Inputs
- `formula: str` (Tableau calc), `table_name: str` (for qualifying field refs).

## Outputs
- `TranslationResult(dax: str | None, reason: str | None)`.
  `dax` set ⇔ fully supported; otherwise `dax is None` and `reason` explains why.

## Behaviour (data-driven)
- `functions.py` holds:
  - `SUPPORTED_FUNCS`: Tableau→DAX name map (SUM, AVG→AVERAGE, MIN, MAX, COUNT,
    COUNTD→DISTINCTCOUNT, ABS, ROUND, LEN, UPPER, LOWER, LEFT, RIGHT, MID, YEAR,
    MONTH, DAY, ISNULL, ...).
  - `UNSUPPORTED_MARKERS`: substrings that immediately disqualify (WINDOW_, RUNNING_,
    INDEX(, RANK(, LOOKUP(, FIRST(, LAST(, FIXED, INCLUDE, EXCLUDE, SCRIPT_, RAWSQL).
- `translator.py`:
  1. Reject if any unsupported marker present.
  2. Qualify field refs `[F]` → `'Table'[F]`.
  3. Rewrite `IF a THEN b ELSE c END` → `IF(a, b, c)`; `ELSEIF`→ nested.
  4. `ZN(x)`→`COALESCE(x,0)`, `IFNULL(a,b)`→`COALESCE(a,b)`, `a/b`→`DIVIDE(a,b)`.
  5. Map remaining function names via `SUPPORTED_FUNCS`; if a function-like token is
     not supported → return `dax=None` with the offending name.

## Edge cases
| Case | Handling |
|---|---|
| Plain field passthrough `[Sales]` | qualify → `'T'[Sales]` |
| Unknown function `FOO(...)` | `dax=None`, reason names `FOO` |
| Unbalanced brackets | `dax=None`, reason "could not parse" |

## Acceptance
- Supported fixtures translate to expected DAX (snapshot).
- Every unsupported fixture returns `dax=None` with a non-empty reason. No guesses.
