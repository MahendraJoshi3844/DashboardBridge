"""Stage 2 — Parse. Raw .twb bytes -> Workbook IR. See docs/specs/modules/parse.md.

## How the parser is configured, and why it is stated rather than defaulted (`P7.4`)

Every security-relevant property of this parser used to come from lxml's
defaults. They are safe today and they are somebody else's decision: lxml 4.x
resolved entities by default, so a version bump was all that stood between this
and XXE, and nothing would have failed. They are passed explicitly now.

`huge_tree=True` was the one deliberate weakening, and it turned off libxml2's
own resource limits: 100,000 levels of nesting parsed happily with it and stop
at 256 without it. It bought nothing measurable - the suite passes without it.
A text node up to 10 MB still reads whole; past that libxml2 2.14 truncates it,
2.11 does not, and the parser refuses it on both so the answer does not depend
on which wheel is installed.

It could not simply be removed, because `recover=True` makes a hit limit
**silent**: 20,001 elements in, 257 out, no exception. So the limit is now
detected and refused. Ordinary malformation is untouched - the unescaped `&`
that `recover=True` exists for still parses - because a resource limit is
distinguished by its error *type* and not by its severity. libxml2 marks nearly
every real-world malformation FATAL, so refusing on severity would have
rejected exactly the workbooks the flag was added to tolerate.
"""

from __future__ import annotations

from lxml import etree

from t2pbi.core.parse.dashboards import parse_dashboards
from t2pbi.core.parse.datasources import parse_datasources
from t2pbi.core.parse.parameters import parse_parameters
from t2pbi.core.parse.worksheets import parse_worksheets
from t2pbi.ir import Severity, Table, Workbook


class ParseLimitExceeded(ValueError):
    """The document hit a parser resource limit and was not read in full.

    A `ValueError` so that callers already handling unreadable input keep
    working, and its own type so that "too big to read safely" stays
    distinguishable from "not a workbook".
    """


def _parser() -> etree.XMLParser:
    """The one parser. Two would be two configurations, one of them unhardened.

    * `recover=True` tolerates the minor malformations real workbooks contain.
    * `huge_tree` is left off, restoring libxml2's depth and size limits.
    * `resolve_entities` off and `load_dtd` off keep an external entity from
      being fetched. They do **not** stop expansion in an attribute value,
      which libxml2 always substitutes - measured at about 750-fold before its
      own guard fires. Both are lxml's current defaults, and lxml 4.x defaulted
      the first to True, which is exactly why they are written down.
    * `no_network=True` because a parser is not a thing that should be able to
      fetch anything, and `LOCAL_ONLY` is not a mode the parser knows about.
    """
    return etree.XMLParser(
        recover=True,
        huge_tree=False,
        resolve_entities=False,
        load_dtd=False,
        dtd_validation=False,
        no_network=True,
    )


#: The errors that mean content was *dropped* rather than repaired.
#:
#: `ERR_INTERNAL_ERROR` is how libxml2 reports the depth limit, message and all.
#: `ERR_ENTITY_LOOP` is its entity-amplification guard: measured, an attribute
#: entity expands about 750-fold before this fires, and past that the whole
#: element is silently discarded under `recover=True`.
#:
#: `ERR_RESOURCE_LIMIT` is how libxml2 2.14+ reports *both* of those limits.
#: The limits did not change, only the type they are filed under, so a newer
#: libxml2 (lxml's Linux wheels ship one before its Windows wheels do) turned
#: the refusal back into silent truncation. Measured on 2.11.9 and 2.14.6.
#:
#: Type, not severity. libxml2 calls almost every real-world malformation FATAL,
#: including the unescaped `&` that `recover=True` exists to tolerate, so
#: refusing on severity would reject the workbooks the flag was added for.
_CONTENT_LOST_ERRORS = frozenset(
    {
        etree.ErrorTypes.ERR_INTERNAL_ERROR,
        etree.ErrorTypes.ERR_ENTITY_LOOP,
        etree.ErrorTypes.ERR_RESOURCE_LIMIT,
    }
)


#: libxml2's `XML_MAX_TEXT_LENGTH`, enforced here as well as there.
#:
#: libxml2 2.14 truncates a text node past this without `huge_tree` and says so
#: (`ERR_RESOURCE_LIMIT`); 2.11 has no such limit and reads it whole. lxml's
#: Linux wheels ship the first and its Windows wheels the second, so the same
#: workbook converted on one and was refused on the other. Checking it
#: ourselves makes the answer the same everywhere. Attribute values need no
#: check of their own: both versions already refuse one this size.
_MAX_TEXT_BYTES = 10_000_000


def parse_workbook(twb_bytes: bytes) -> Workbook:
    parser = _parser()
    root = etree.fromstring(twb_bytes, parser=parser)
    _refuse_if_truncated(parser)
    _refuse_oversized_text(root)
    if root is None:
        raise ValueError("Could not parse .twb XML.")

    wb = Workbook(version=root.get("version", ""))
    parse_parameters(root, wb)
    parse_datasources(root, wb)
    _disambiguate_table_names(wb)
    parse_worksheets(root, wb)
    parse_dashboards(root, wb)
    return wb


def _refuse_if_truncated(parser: etree.XMLParser) -> None:
    """Refuse a tree that a parser guard cut short.

    `recover=True` returns whatever it managed to build, so without this a
    workbook silently missing everything below nesting level 256 - or missing
    the element that used an over-expanded entity - is indistinguishable from
    one that never had it. That is the failure mode the whole project is
    written against, and it is the reason libxml2's limits could not simply be
    turned back on and left there.
    """
    for entry in parser.error_log:
        if entry.type in _CONTENT_LOST_ERRORS:
            raise ParseLimitExceeded(
                "This workbook hit a parser limit and was not read in full, so "
                f"nothing was converted from it: {entry.message}. This is a "
                "limit, not a damaged file - a workbook nested past 256 levels, "
                "or an entity expanding far past what a document needs."
            )


def _refuse_oversized_text(root: etree._Element | None) -> None:
    """Refuse a text node past `_MAX_TEXT_BYTES`, whichever libxml2 read it.

    The character count screens first because encoding every node would cost
    a copy of the document; a string can only exceed the byte limit once it
    is at least a quarter of it in characters.
    """
    if root is None:
        return
    for element in root.iter():
        for text in (element.text, element.tail):
            if (
                text
                and len(text) > _MAX_TEXT_BYTES // 4
                and len(text.encode("utf-8")) > _MAX_TEXT_BYTES
            ):
                raise ParseLimitExceeded(
                    "This workbook hit a parser limit and was not read in full, "
                    "so nothing was converted from it: a single text value is "
                    f"larger than {_MAX_TEXT_BYTES:,} bytes. This is a limit, not "
                    "a damaged file - no workbook content Tableau writes needs a "
                    "text value that size."
                )


def _disambiguate_table_names(wb: Workbook) -> None:
    """Give same-named tables from different datasources distinct names.

    Tables are written to one file per name and referenced by name in DAX, so a
    collision silently overwrites one table with another. Runs before anything
    else references a table name; relationships are rewritten to match.

    The rewrite is scoped to the datasource whose table was renamed. A single
    name -> name map across the whole workbook cannot be right: the *first*
    datasource to claim a name keeps it, so rewriting every relationship that
    mentions that name moved the first datasource's own relationships onto the
    second's table and emitted a join the workbook never had. Scoping needs
    `source_id`, which is Tableau's internal per-datasource identifier.
    """
    seen: dict[str, Table] = {}
    for ds in wb.datasources:
        renames: dict[str, str] = {}
        for table in ds.tables:
            if table.name not in seen:
                seen[table.name] = table
                continue
            new_name = f"{ds.name} {table.name}"
            suffix = 2
            while new_name in seen:
                new_name = f"{ds.name} {table.name} {suffix}"
                suffix += 1
            renames[table.name] = new_name
            wb.add_flag(
                item=table.name,
                severity=Severity.INFO,
                reason=(
                    f"Two datasources define a table named '{table.name}'; renamed "
                    f"this one to '{new_name}' so neither is overwritten."
                ),
                stage="parse",
            )
            table.name = new_name
            seen[new_name] = table

        for rel in wb.relationships:
            if rel.datasource_id == ds.source_id:
                rel.from_table = renames.get(rel.from_table, rel.from_table)
                rel.to_table = renames.get(rel.to_table, rel.to_table)
