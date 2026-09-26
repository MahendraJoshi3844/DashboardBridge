"""Write a Power BI `filterConfig` block.

Everything in this module is read out of Power BI Desktop's own bundle
(`WebView2Resources/minerva/scripts/desktop.min.js`) rather than inferred, for
the reason recorded after the first Desktop round trip: *nothing about this
format is confirmed until Desktop says so*, and Desktop's serializer is better
evidence than any documentation of it.

What the bundle says, function by function:

* `FilterConfigurationSerializer.serialize` builds `{filters: [...]}` and omits
  the key entirely when there is nothing in it.
* Each filter is `{name, displayName?, ordinal?, field, type, filter, ...}`,
  where `name` is generated if absent - so a converter that wants deterministic
  output has to supply it.
* `type` comes from the wire enum whose members are the literal strings
  `"Categorical"`, `"Range"`, `"Advanced"`, `"TopN"`, ...
* `field` goes through `serializeExpr`, which is `create(expr, standalone=true)`
  - and `visitEntity` in standalone mode writes `{SourceRef: {Schema, Entity}}`.
* `filter` goes through `serializeFilter`, which returns
  `{Version: 2, From: [...], Where: [...]}`. `From` entries come from
  `SQFromSourceSerializer.visitEntity`: `{Name, Entity, Schema, Type}` with
  `Type` = `EntitySourceType.Table` = `0`. `Where` entries are
  `{Condition, Target?, Annotations?}`, and the conditions are serialised with
  `standalone=false`, so a column there names the `From` alias
  (`{SourceRef: {Source}}`) and *not* the entity.
* `visitIn` -> `{In: {Expressions, Values}}` with `Values` a list of tuples,
  each tuple a list of expressions. `visitNot` -> `{Not: {Expression}}`.
* `visitColumnRef` -> `{Column: {Expression, Property}}`.
* `visitConstant` -> `{Literal: {Value: <encoded>}}`, and Desktop's own decoder
  shows the encoding: text is `'quoted'` with `''` for an embedded quote,
  integers end `L`, doubles `D`, decimals `M`, datetimes are
  `datetime'...'`, and the bare words `null`, `true`, `false` decode to those
  values. Only text and null are written here - see
  `mapping.visual_map._carry_over` for why the rest are refused.

`Schema` is left out of both `SourceRef` and the `From` entry: the serializer
writes it from `expr.schema`, which is undefined for a Power BI model, and
`JSON.stringify` drops undefined keys.
"""

from __future__ import annotations

import hashlib

from t2pbi.core.emit.tmdl import sanitize_name
from t2pbi.core.mapping import NULL_MEMBER, PBIFilter

#: `EntitySourceType.Table`, from `e[e.Table=0]="Table",e[e.Pod=...` in the
#: bundle - the enum `SQFromSourceSerializer.visitEntity` reads `Type` from.
_ENTITY_SOURCE_TABLE = 0

#: `SemanticQuerySerializer.serializeFilter` writes `Version: Version2`, and the
#: enum has `Version2=2`. Desktop's deserializer treats anything below
#: `Version1` as needing a target upgrade, so writing the current version is
#: what keeps the filter out of that legacy path.
_FILTER_VERSION = 2


def _literal(value: str) -> dict:
    """One Tableau member as a Power BI literal expression.

    Only two encodings are produced, and both are proven by Desktop's decoder:
    the bare word `null`, and text as `'value'` with `''` for an embedded
    quote. Anything needing a numeric or date encoding never reaches here -
    `_carry_over` refuses the filter instead, because re-typing an untyped
    member is exactly the guess this converter does not make.
    """
    if value == NULL_MEMBER:
        return {"Literal": {"Value": "null"}}
    return {"Literal": {"Value": "'" + value.replace("'", "''") + "'"}}


def _alias(entity: str) -> str:
    """The `From` alias for a table.

    Desktop generates these (`o`, `o1`, ...) and nothing reads them outside the
    filter that defines them, so any stable choice works. Derived from the
    entity rather than counted, so the same workbook always produces the same
    bytes.
    """
    first = next((c for c in entity if c.isalpha()), "t")
    return first.lower()


def _filter_id(page_name: str, filter_: PBIFilter) -> str:
    """A deterministic id where Desktop would use a random one.

    Seeded with the page as well as the field, so two pages filtering the same
    column do not collide, and with the values, so editing the filter in Tableau
    and re-converting does not silently reuse an id for a different filter.
    """
    seed = "|".join(
        (
            page_name,
            filter_.field.table,
            filter_.field.column,
            "except" if filter_.excludes else "in",
            *filter_.values,
        )
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]


def _one(page_name: str, filter_: PBIFilter) -> dict:
    entity = sanitize_name(filter_.field.table)
    alias = _alias(entity)
    column = filter_.field.column

    condition: dict = {
        "In": {
            "Expressions": [
                {
                    "Column": {
                        "Expression": {"SourceRef": {"Source": alias}},
                        "Property": column,
                    }
                }
            ],
            "Values": [[_literal(v)] for v in filter_.values],
        }
    }
    if filter_.excludes:
        condition = {"Not": {"Expression": condition}}

    return {
        "name": _filter_id(page_name, filter_),
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": entity}},
                "Property": column,
            }
        },
        "type": "Categorical",
        "filter": {
            "Version": _FILTER_VERSION,
            "From": [
                {"Name": alias, "Entity": entity, "Type": _ENTITY_SOURCE_TABLE}
            ],
            "Where": [{"Condition": condition}],
        },
    }


def filter_config(page_name: str, filters: list[PBIFilter]) -> dict | None:
    """The `filterConfig` value for a page, or `None` when there is nothing.

    `None` rather than `{"filters": []}`: Desktop's own serializer returns
    undefined for an empty configuration, so an empty object is a shape it never
    writes and there is no reason to be the first to try it.
    """
    if not filters:
        return None
    return {"filters": [_one(page_name, f) for f in filters]}
