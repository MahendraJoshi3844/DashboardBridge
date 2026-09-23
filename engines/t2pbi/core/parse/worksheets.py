"""Parse <worksheets> into Worksheet IR (visual type + encodings + filters)."""

from __future__ import annotations

import re
from dataclasses import replace

from lxml import etree

from engines.t2pbi.ir import (
    CATEGORY,
    DETAIL,
    FILTER,
    SERIES,
    Severity,
    TOOLTIP,
    VALUE,
    VisualBinding,
    Workbook,
    Worksheet,
)

# A whole shelf operand: optional [datasource]. qualifier plus the [token] itself.
_SHELF_TOKEN_RE = re.compile(r"(?:\[([^\[\]]+)\]\.)?\[([^\[\]]+)\]")

# Tableau encodes shelf fields as "<prefix>:<Field>:<role-kind>". The prefix is
# either a date truncation/part or an aggregation; the trailing kind (ok/qk/nk)
# is presentation metadata we do not need.
_DATE_PARTS = frozenset(
    {
        "yr", "qr", "mn", "wk", "wd", "dy", "hr", "mi", "se", "mdy",
        "tyr", "tqr", "tmn", "twk", "tdy", "thr", "tmi", "tse",
    }
)
_AGGREGATIONS = frozenset(
    {"sum", "avg", "cnt", "cntd", "min", "max", "median", "stdev", "var", "attr"}
)
# "usr" marks a reference to a user-defined calculated field; the field part is
# that calc's internal name, which resolves against the datasource columns.
_USER_CALC = "usr"

# Shelf tokens that are not real fields and must never become a visual binding.
_SPECIAL_TOKENS = frozenset({"Multiple Values", "Measure Values", "Measure Names"})
_OBJECT_ID_PREFIX = "__tableau_internal_object_id__"


def _unresolvable(raw: str, field: str, datasource: str | None) -> VisualBinding:
    return VisualBinding(
        raw=raw, field=field, datasource=datasource, resolvable=False
    )


def decode_shelf_ref(token: str) -> VisualBinding:
    """Decode one ``[datasource].[agg:Field:kind]`` shelf operand.

    Tableau writes shelf references in an internal encoding; taking the bracket
    contents literally binds visuals to columns that do not exist.
    """
    match = _SHELF_TOKEN_RE.fullmatch(token.strip())
    if match is None:
        return _unresolvable(token, token, None)
    datasource, inner = match.group(1), match.group(2)

    if inner in _SPECIAL_TOKENS or _OBJECT_ID_PREFIX in inner:
        return _unresolvable(token, inner, datasource)

    parts = inner.split(":")
    if len(parts) == 1:
        # Already a plain field name (older/simpler workbooks).
        return VisualBinding(raw=token, field=inner, datasource=datasource)
    if len(parts) != 3 or not parts[0] or not parts[1]:
        # ":Measure Names", or a nested table calc like "pcto:cnt:<obj>:qk:1".
        return _unresolvable(token, inner, datasource)

    prefix, field, _kind = parts
    if _OBJECT_ID_PREFIX in field:
        return _unresolvable(token, field, datasource)

    lowered = prefix.lower()
    return VisualBinding(
        raw=token,
        field=field,
        datasource=datasource,
        aggregation=lowered if lowered in _AGGREGATIONS else None,
        date_part=lowered if lowered in _DATE_PARTS else None,
        resolvable=lowered in _AGGREGATIONS
        or lowered in _DATE_PARTS
        or lowered in {"none", _USER_CALC},
    )


def parse_shelf_expression(text: str | None) -> list[VisualBinding]:
    """Decode every operand of a rows/cols shelf expression, in order."""
    if not text:
        return []
    return [decode_shelf_ref(m.group(0)) for m in _SHELF_TOKEN_RE.finditer(text)]

# Tableau mark class -> normalized visual type (v1 set).
_MARK_MAP = {
    "Bar": "bar",
    "Line": "line",
    "Area": "area",
    "Text": "table",
    "Square": "table",
    "Automatic": "bar",
    "Circle": "scatter",
    "Shape": "scatter",
    "Pie": "pie",
}


def _member_value(raw: str) -> str:
    """One selected value, as a person would recognise it.

    A `:Measure Names` filter's members are not data values - they are shelf
    references, so the raw text is
    `[federated.0a01cod...].[min:Base (Variable):qk]`. Printing that in a
    migration report as "this filter keeps only ..." shows a consultant machine
    text where they expect a value they know, which is worse than showing
    nothing: it looks like data and is not.

    So a member that is a shelf reference is decoded to the field it names, and
    an ordinary value is just unquoted.
    """
    value = raw.strip().strip('"')
    if value.startswith("[") and "].[" in value:
        decoded = decode_shelf_ref(value)
        return decoded.field or value
    return value


def _members_under(element: etree._Element) -> tuple[str, ...]:
    """Every member named anywhere below `element`, sorted and deduplicated."""
    return tuple(
        sorted(
            {
                _member_value(child.get("member") or "")
                for child in element.findall(".//groupfilter[@function='member']")
                if child.get("member")
            }
        )
    )


def _what_the_filter_does(filter_el: etree._Element) -> dict:
    """Read a `<filter>`'s content, not just the field it names.

    Only the field was kept before, so `Category, all values` and
    `Category, two values` arrived downstream as the same object - and the
    report told a consultant to recreate both. On Superstore that was 65 filters
    of 83 reported as manual work that remove nothing.

    Tableau writes several shapes here and they mean different things:

    * `level-members` with no member children is **all values**. It is a filter
      shelf entry that restricts nothing.
    * `union`/`member` children name the selected values. Those values *are* the
      filter, and without them "recreate this" is a puzzle.
    * `<min>`/`<max>`, or a `range` groupfilter's `from`/`to`, is a range.

    Anything unrecognised is treated as restricting. That direction is
    deliberate: reporting real work as none is the failure that matters, and
    the reverse is only noise.
    """
    group = filter_el.find("./groupfilter")

    # `except` first, and by shape rather than by descendant. Its members are
    # the ones *removed*; a `.//member` sweep sees the same leaves as a union
    # and reads the filter backwards. Superstore's one `except` - every city
    # but the blanks - was reported as "keeps only: %null%".
    if group is not None and group.get("function") == "except":
        removed = _members_under(group)
        if removed:
            return {"restricts": True, "excludes": True, "members": removed}
        # `except` with nothing to remove keeps the whole level.
        return {"restricts": False}

    members = _members_under(filter_el)
    if members:
        return {"restricts": True, "members": members}

    lower = filter_el.findtext("min") or filter_el.findtext(".//min")
    upper = filter_el.findtext("max") or filter_el.findtext(".//max")
    if group is not None and group.get("function") == "range":
        lower = lower or group.get("from")
        upper = upper or group.get("to")
    if lower is not None or upper is not None:
        return {"restricts": True, "minimum": lower, "maximum": upper}

    if group is not None and group.get("function") == "level-members":
        # Tableau's "all". The shelf entry exists; nothing is excluded.
        return {"restricts": False}

    return {"restricts": True}


def parse_worksheets(root: etree._Element, wb: Workbook) -> None:
    for ws_el in root.findall("./worksheets/worksheet"):
        name = ws_el.get("name") or "Sheet"

        mark_el = ws_el.find(".//mark")
        mark_class = mark_el.get("class") if mark_el is not None else None
        visual_type = _MARK_MAP.get(mark_class or "", "unknown")
        if visual_type == "unknown":
            wb.add_flag(
                item=name,
                severity=Severity.WARNING,
                reason=f"Unrecognized mark type '{mark_class}'; mapped to 'unknown'.",
                stage="parse",
            )
        elif mark_class == "Automatic":
            # Tableau picks the shape at render time from the shelf types, so any
            # single choice here is inference, not a faithful reading of the file.
            wb.add_flag(
                item=name,
                severity=Severity.WARNING,
                reason=(
                    "Mark type is 'Automatic' (Tableau chooses the shape at render "
                    f"time); generated as '{visual_type}' - verify the chart type."
                ),
                stage="parse",
            )

        rows_el = ws_el.find(".//rows")
        cols_el = ws_el.find(".//cols")
        bindings = [
            replace(binding, role=CATEGORY)
            for binding in parse_shelf_expression(
                cols_el.text if cols_el is not None else None
            )
        ] + [
            replace(binding, role=VALUE)
            for binding in parse_shelf_expression(
                rows_el.text if rows_el is not None else None
            )
        ]
        # Everything else a field can be dragged onto. These were read by
        # nothing and reported by nothing, so a workbook's colour, size, text
        # and tooltip placements simply vanished - 31 of them in Superstore
        # alone. Carrying them into the model is what lets the mapper report
        # each one instead of the workbook quietly losing it.
        bindings += _other_shelves(ws_el)

        # Tableau repeats a <filter> per pane and per datasource dependency, so the
        # same field appears many times; keep one entry per field, in order.
        filters: list[VisualBinding] = []
        seen_filters: set[str] = set()
        for f in ws_el.findall(".//filter"):
            column = f.get("column")
            if not column:
                continue
            ref = decode_shelf_ref(column)
            if ref.field in seen_filters:
                continue
            seen_filters.add(ref.field)
            filters.append(replace(ref, role=FILTER, **_what_the_filter_does(f)))

        wb.worksheets.append(
            Worksheet(
                name=name,
                visual_type=visual_type,
                bindings=bindings,
                filters=filters,
            )
        )


#: The shelves a field can be dragged onto besides rows and columns, and what
#: each one means in the model's vocabulary. Tableau's `text` shelf is a label
#: drawn on the mark, which is a detail of the mark rather than a series.
_OTHER_SHELVES = {
    "color": SERIES,
    "size": DETAIL,
    "text": DETAIL,
    "label": DETAIL,
    "detail": DETAIL,
    "shape": DETAIL,
    "tooltip": TOOLTIP,
}


def _other_shelves(ws_el: etree._Element) -> list[VisualBinding]:
    """Colour, size, text, tooltip and the rest, in a stable order.

    Read but not bound: the mapper reports each one rather than guessing which
    Power BI well it belongs in. Reading them is the point - before this they
    were invisible, which made a dropped colour encoding indistinguishable from
    a worksheet that never had one.

    Deduplicated per shelf and field, because Tableau repeats a shelf element
    per pane.
    """
    found: list[VisualBinding] = []
    seen: set[tuple[str, str]] = set()
    for shelf, role in _OTHER_SHELVES.items():
        for element in ws_el.findall(f".//{shelf}"):
            column = element.get("column")
            if not column:
                continue
            binding = decode_shelf_ref(column)
            key = (shelf, binding.field)
            if key in seen:
                continue
            seen.add(key)
            found.append(replace(binding, role=role))
    return found
