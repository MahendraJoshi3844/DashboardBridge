# Module Spec — Extract

**Code:** `engines/t2pbi/core/extract.py`

## Purpose
Stage 1. Turn an input path (`.twb` or `.twbx`) into the raw `.twb` XML bytes plus a
resource map — without ever unpacking full data extracts.

## Inputs
- `path: str | Path` to a `.twb` or `.twbx` file.

## Outputs
- `ExtractResult(twb_bytes: bytes, source_format: str, resources: dict[str,int])`
  where `resources` maps member name → size (schema info only; no extract bytes read).

## Behaviour
- `.twb`: read the file bytes directly; `source_format="twb"`.
- `.twbx`: open as ZIP; locate the single top-level `*.twb` member; read only that
  member's bytes; record other members' names+sizes lazily (never read their data).
- Validate the bytes look like a Tableau workbook (root `<workbook>`); else raise
  `InvalidWorkbookError`.

## Edge cases
| Case | Handling |
|---|---|
| Not a zip and not xml | `InvalidWorkbookError` with clear message |
| `.twbx` without a `.twb` member | `InvalidWorkbookError` |
| Multiple `.twb` members | pick the top-level one; if ambiguous, raise |
| Huge extract members | record name+size only; never read bytes |

## Acceptance
- Given a `.twbx`, returns the `.twb` bytes and does not read any `Data/` member bytes.
- Given a malformed file, raises `InvalidWorkbookError`, never a raw zip/lxml error.
