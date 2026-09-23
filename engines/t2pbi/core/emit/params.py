"""Emit Power BI what-if parameters (TMDL) from Tableau parameters.

A range what-if parameter is a calculated table over GENERATESERIES plus a value
measure that reads the slicer selection. A list parameter becomes a single-column
calculated table built from its members plus the same value measure. We never
invent a domain: if bounds are missing we fall back to sensible defaults derived
only from the captured default value.
"""

from __future__ import annotations

import re

from engines.t2pbi.core.emit.tmdl import sanitize_name
from engines.t2pbi.ir import Parameter, Severity, Workbook

_NUMERIC = {"integer", "real"}


def value_measure_name(p: Parameter) -> str:
    """Stable name of the measure that exposes a parameter's selected value."""
    return f"{p.display_name} Value"


def _is_numeric(p: Parameter) -> bool:
    return p.datatype in _NUMERIC


def _num(value: str | None, fallback: str) -> str:
    if value is None or value.strip() == "":
        return fallback
    try:
        f = float(value)
    except ValueError:
        return fallback
    return str(int(f)) if f.is_integer() else repr(f)


def param_table_tmdl(p: Parameter, workbook: Workbook | None = None) -> str:
    """Render one what-if parameter table (+ value measure) as TMDL."""
    name = p.display_name
    col = sanitize_name(name)
    quoted = f"'{sanitize_name(name)}'"
    lines = [f"table {quoted}"]

    if p.kind == "list" or not _is_numeric(p):
        members = p.members or ([p.default_value] if p.default_value else [])
        rows = ", ".join(_quote_member(m) for m in members) or '""'
        lines += [
            f"\tcolumn '{col}'",
            "\t\tdataType: string",
            "\t\tsourceColumn: Value",
            "",
            f"\tpartition {quoted} = calculated",
            "\t\tmode: import",
            f"\t\tsource = {{{rows}}}",
            "",
        ]
        default = _quote_member(p.default_value) if p.default_value else '""'
    else:
        lo = _num(p.min_value, "0")
        step = _num(p.step, "1")
        hi = _upper_bound(p, lo, workbook)
        dtype = "int64" if p.datatype == "integer" else "double"
        lines += [
            f"\tcolumn '{col}'",
            f"\t\tdataType: {dtype}",
            "\t\tsourceColumn: Value",
            "",
            f"\tpartition {quoted} = calculated",
            "\t\tmode: import",
            f"\t\tsource = GENERATESERIES({lo}, {hi}, {step})",
            "",
        ]
        default = _num(p.default_value, lo)

    lines += [
        f"\tmeasure '{sanitize_name(value_measure_name(p))}' = "
        f"SELECTEDVALUE({quoted}[{col}], {default})",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _upper_bound(p: Parameter, lo: str, workbook: Workbook | None) -> str:
    """Pick the range's top end.

    Tableau range parameters may be open-ended, but GENERATESERIES needs a bound.
    Falling back to the default value pins the slider at its own maximum, so
    instead extend the same distance again above the default and say so.
    """
    if p.max_value is not None and p.max_value.strip() != "":
        return _num(p.max_value, "100")

    default = float(_num(p.default_value, "100"))
    low = float(lo)
    top = default + max(default - low, abs(default) or 1.0)
    bound = str(int(top)) if float(top).is_integer() else repr(top)
    if workbook is not None:
        workbook.add_flag(
            item=p.display_name,
            severity=Severity.WARNING,
            reason=(
                f"Tableau parameter has no upper bound; used {bound} so the slider "
                "can move past its default. Adjust the range to suit your data."
            ),
            stage="emit",
        )
    return bound


def _quote_member(raw: str) -> str:
    """Normalize a Tableau list member into a clean DAX string literal.

    Tableau stores members already quoted and backslash-escapes specials
    (e.g. '"\\% quota ascending"'); strip the quoting and escapes, then re-quote.
    """
    s = (raw or "").strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    s = re.sub(r"\\(.)", r"\1", s)  # drop Tableau escape backslashes
    return '"' + s.replace('"', "") + '"'
