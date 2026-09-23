"""Tableau datatype -> TMDL dataType mapping."""

from __future__ import annotations

_MAP = {
    "integer": "int64",
    "real": "double",
    "string": "string",
    "boolean": "boolean",
    "date": "dateTime",
    "datetime": "dateTime",
}


# Tableau datatype -> Power Query (M) type, used to type the partition schema.
_M_MAP = {
    "integer": "Int64.Type",
    "real": "number",
    "string": "text",
    "boolean": "logical",
    "date": "date",
    "datetime": "datetime",
}


def tmdl_datatype(tableau_datatype: str) -> str:
    return _MAP.get((tableau_datatype or "").lower(), "string")


def m_datatype(tableau_datatype: str) -> str:
    return _M_MAP.get((tableau_datatype or "").lower(), "text")


def is_known(tableau_datatype: str) -> bool:
    return (tableau_datatype or "").lower() in _MAP
