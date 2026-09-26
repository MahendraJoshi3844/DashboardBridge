---
name: twbx-anatomy
description: Reference for the structure of Tableau .twb/.twbx files and how to map their XML elements to the t2pbi Intermediate Representation. Use when parsing Tableau workbooks, locating fields/calcs/relationships in the XML, or deciding how a Tableau element maps to Power BI.
---

# Tableau .twb / .twbx Anatomy → t2pbi IR

Implementation lives in `t2pbi/core/extract.py` and `t2pbi/core/parse/`.
The IR is `t2pbi/ir/model.py`.

## File shapes

- **`.twb`** — one XML document, root `<workbook>`.
- **`.twbx`** — a ZIP holding the `.twb` plus `Data/` extracts and resources.
  `extract.py` reads **only** the `.twb` member and records the others' sizes from
  the zip directory without reading their bytes. Prefer a top-level `.twb`; a
  nested copy under `Backup/` is a decoy. Two at the top level is genuinely
  ambiguous and is rejected.

## Where things live

| Tableau XML | Maps to IR |
|---|---|
| `<datasources>/<datasource>` | `DataSource` (`source_id` = the raw `name` attr) |
| `<datasource name='Parameters'>` | `Workbook.parameters`, **not** a DataSource |
| `.//object-graph//object` | one `Table` per object, named by `caption` |
| `.//metadata-record[@class='column']` | `Column`, attributed to its `<object-id>` |
| datasource-level `<column>` | role, caption, and calculations |
| `<column>` with `<calculation formula=...>` | `Column.formula` |
| `.//relationship` + endpoint `object-id`s | `Workbook.relationships` |
| `<worksheets>/<worksheet>` | `Worksheet` |
| `.//mark[@class]` | `Worksheet.visual_type` |
| `<rows>` / `<cols>` text | `Worksheet.encoding.rows/cols` as `list[ShelfRef]` |
| `<filter column=...>` | `Worksheet.filters` as `list[ShelfRef]` |
| `<dashboards>/<dashboard>` zones | `Dashboard.sheet_names` |

## Shelf references are encoded — decode them

**The single most costly trap in this codebase.** Real Tableau does not write
plain field names on a shelf. It writes:

```
[federated.10nnk8d1vgmw8q17yu76u06pnbcj].[sum:Sales:qk]
```

Taking the bracket contents literally binds every visual to a column named
`sum:Sales:qk`, which exists nowhere. `worksheets.py::decode_shelf_ref` splits
`<prefix>:<Field>:<role-kind>`:

- prefix is a **date part** (`yr qr mn wk dy hr mi se`, `t`-prefixed truncations),
  an **aggregation** (`sum avg cnt cntd min max median attr`), `none`, or `usr`
  for a user-defined calc (the field part is then the calc's internal name).
- Anything else is **not resolvable** and must be flagged, never guessed:
  `[:Measure Names]`, `[Multiple Values]`, nested table calcs with more than
  three colon-separated parts (`pcto:cnt:<obj>:qk:1`), and
  `__tableau_internal_object_id__`.

Keep the datasource qualifier. Field resolution is scoped by it, so a name
present in two datasources binds to the right table.

**Hand-written fixtures must use the real encoding.** `tests/fixtures/sample.twb`
originally used plain names, which is why a completely broken visual layer passed
32 tests.

## Federation

A Tableau datasource federates several physical tables into one logical source.
Model each object as its own Power BI table, or columns land in the wrong place
and relationships have no endpoints. Columns named
`__tableau_internal_object_id__` are join keys, not data — drop them and flag it.

Two datasources may define a same-named table. Names are used for filenames and
in DAX, so a collision silently overwrites one with the other;
`parse/__init__.py::_disambiguate_table_names` renames and flags, and rewrites
relationships to match.

## Parsing rules

1. `parse_workbook` uses `etree.fromstring(..., recover=True, huge_tree=True)`.
   Note this is a full parse, not the `lxml.iterparse` streaming CLAUDE.md calls
   for — fine at Superstore's 1.1 MB, revisit if large workbooks appear.
2. `caption` is the display name and often differs from the internal `name`.
   Carry both: calcs reference either, and TMDL emits the caption.
3. Never read extract data. Schema only.
4. Anything ambiguous or unsupported becomes a `ConversionFlag`, never a guess.

## Gotchas

- A parameter's `<range>` may have `min` but no `max`. GENERATESERIES needs a
  bound, so one is derived and flagged — do not silently use the default value as
  the maximum, which pins the slider at its own top end.
- List parameter members arrive quoted and backslash-escaped
  (`'"\\% quota ascending"'`). Strip both before re-quoting.
- `mark class='Automatic'` means Tableau picks the shape at render time. Any
  single choice is inference, so it is flagged as one.
- Tableau repeats `<filter>` per pane and per datasource dependency; dedupe by
  field or one sheet yields dozens of identical flags.
- Live-connection workbooks have no extract. Emit the schema with a typed empty
  partition and flag the table for re-pointing.
