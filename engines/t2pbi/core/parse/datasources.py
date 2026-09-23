"""Parse <datasources> into DataSource/Table/Column IR.

Tableau federates several physical tables ("objects" like Orders/People/Returns)
into one logical datasource. We model each object as its own Power BI table so that
columns land in the right place and relationships have real endpoints. Datasources
with no object-graph (simple single-table sources) fall back to one table.
"""

from __future__ import annotations

from lxml import etree

from engines.t2pbi.ir import Column, DataSource, Relationship, Severity, Table, Workbook

# Tableau emits federation join-key columns under this synthetic name. They are not
# real data columns and must never be written to the model.
_OBJECT_ID_PREFIX = "__tableau_internal_object_id__"


def _clean_name(raw: str | None) -> str:
    """Strip Tableau's [brackets] from a field/identifier name."""
    if not raw:
        return ""
    return raw.strip().lstrip("[").rstrip("]")


def _is_object_id(name: str) -> bool:
    return _OBJECT_ID_PREFIX in name


def parse_datasources(root: etree._Element, wb: Workbook) -> None:
    for ds_el in root.findall("./datasources/datasource"):
        if ds_el.get("name") == "Parameters":
            continue  # handled by parse_parameters
        _parse_one_datasource(ds_el, wb)


def _connection_of(
    ds_el: etree._Element, is_extract: bool
) -> tuple[str, str | None]:
    """What this datasource actually connects to, and where that is.

    **`federated` is a wrapper, not a connection.** Every Tableau file source is
    a `federated` shell around a `<named-connection>` holding the real thing -
    `excel-direct` with a filename, `textscan` with a directory and a filename,
    `sqlserver` with a server and a database. Reading the outer element gave
    `federated` for all three of Superstore's sources, which is like reporting
    that a parcel arrived in a box.

    The location matters because the converted model carries schema and no rows,
    deliberately (`CLAUDE.md`: never load a full data extract, only its schema).
    Pointing the model at the user's own copy of the data is the one thing they
    must do to make it useful, and they cannot do it if the converter quietly
    forgot where the data was.
    """
    inner = ds_el.find(".//named-connections/named-connection/connection")
    conn_el = inner if inner is not None else ds_el.find(".//connection")
    if conn_el is None:
        return ("extract" if is_extract else "unknown"), None

    kind = conn_el.get("class") or ("extract" if is_extract else "unknown")
    return kind, _location_of(conn_el)


#: Tableau's connection classes, in words a person reading a migration report
#: would use. `excel-direct` and `textscan` are how Tableau names them
#: internally; nobody calls a spreadsheet an excel-direct.
_KIND_IN_WORDS = {
    "excel-direct": "an Excel file",
    "textscan": "a text or CSV file",
    "hyper": "a Tableau extract",
    "extract": "a Tableau extract",
    "sqlserver": "a SQL Server database",
    "postgres": "a PostgreSQL database",
    "oracle": "an Oracle database",
    "mysql": "a MySQL database",
    "snowflake": "a Snowflake warehouse",
    "bigquery": "a BigQuery dataset",
    "redshift": "a Redshift cluster",
    "googlesheets": "a Google Sheet",
    "webdata-direct": "a web data connector",
}


def _kind_in_words(connection: str) -> str:
    """The connection kind as a person would say it.

    Falls back to the raw class rather than to "a data source": an unmapped
    class is still a fact about the workbook, and printing a vaguer word than
    the one we have would be losing information to look tidy.
    """
    known = _KIND_IN_WORDS.get(connection)
    if known:
        return known
    article = "an" if connection[:1].lower() in "aeiou" else "a"
    return f"{article} {connection} source"


def _location_of(conn_el: etree._Element) -> str | None:
    """A file path, or `server/database`. `None` when the workbook is silent.

    `None` rather than an empty string or a placeholder: "we do not know where
    this came from" and "it came from nowhere" are different facts, and only one
    of them is worth printing next to an instruction to go and find the file.
    """
    filename = (conn_el.get("filename") or "").strip()
    directory = (conn_el.get("directory") or "").strip()
    if filename:
        # `textscan` splits the path across two attributes; a person wants one.
        joined = f"{directory.rstrip('/')}/{filename}" if directory else filename
        return joined

    server = (conn_el.get("server") or "").strip()
    database = (conn_el.get("dbname") or "").strip()
    if server and database:
        return f"{server}/{database}"
    return server or database or None


def _parse_one_datasource(ds_el: etree._Element, wb: Workbook) -> None:
    ds_name = ds_el.get("caption") or _clean_name(ds_el.get("name")) or "DataSource"

    is_extract = ds_el.find(".//connection[@class='hyper']") is not None or (
        ds_el.find(".//extract") is not None
    )
    connection, source_location = _connection_of(ds_el, is_extract)

    # Datasource-level <column> elements carry role, caption, and calculations.
    decl_by_name: dict[str, etree._Element] = {}
    for col_el in ds_el.findall("./column"):
        nm = _clean_name(col_el.get("name"))
        if nm:
            decl_by_name[nm] = col_el

    # Physical columns + their owning object come from metadata-records.
    objects = _object_captions(ds_el)
    phys = _physical_columns(ds_el)  # ordered list of (object_id, col_name, datatype)

    tables: list[Table] = []
    if phys and objects:
        tables = _build_object_tables(ds_name, objects, phys, decl_by_name, wb)
    else:
        tables = [_build_single_table(ds_name, ds_el, decl_by_name, wb)]

    # Calculated fields (declared columns with a <calculation>) -> attach to the
    # primary (largest) table as measures.
    _attach_calculations(tables, decl_by_name, ds_name, wb)

    wb.datasources.append(
        DataSource(
            name=ds_name,
            connection=connection,
            source_location=source_location,
            tables=tables,
            is_extract=is_extract,
            source_id=ds_el.get("name") or "",
        )
    )

    # Say that the model will have no rows, and where the rows were.
    #
    # Power BI Desktop opens a converted project and warns that "some of the
    # tables have incomplete or no data". That is correct and by design, and
    # for a long time this product said nothing about it - 185 flags on
    # Superstore and not one mentioned data. So the single action needed to
    # make the converted model useful was the one thing the migration report
    # left out.
    where = (
        f" The data was at {source_location}."
        if source_location
        else " This workbook does not record where the data was."
    )
    wb.add_flag(
        item=ds_name,
        severity=Severity.MANUAL,
        reason=(
            f"Connect this data source. It is {_kind_in_words(connection)}, and "
            "the converted model carries its schema and no rows - the converter "
            "reads structure and never a full extract, so nothing is copied "
            f"out of your data.{where} Point the table's source at your copy "
            "and refresh."
        ),
        stage="parse",
    )

    _parse_relationships(ds_el, objects, wb)


def _object_captions(ds_el: etree._Element) -> dict[str, str]:
    """object-id -> readable caption (e.g. 'Orders_6D2E...' -> 'Orders')."""
    out: dict[str, str] = {}
    for obj in ds_el.findall(".//object-graph//object"):
        oid = obj.get("id")
        cap = obj.get("caption")
        if oid:
            out[oid] = cap or oid
    return out


def _physical_columns(ds_el: etree._Element) -> list[tuple[str, str, str]]:
    """(object_id, column_name, tableau_datatype) from metadata-records, ordered."""
    out: list[tuple[str, str, str]] = []
    for rec in ds_el.findall(".//metadata-record[@class='column']"):
        name = _clean_name(_text(rec, "local-name") or _text(rec, "remote-name"))
        if not name or _is_object_id(name):
            continue
        oid = _clean_name(_text(rec, "object-id"))
        datatype = _text(rec, "local-type") or "string"
        out.append((oid, name, datatype))
    return out


def _text(el: etree._Element, tag: str) -> str | None:
    child = el.find(tag)
    return child.text if child is not None else None


def _build_object_tables(
    ds_name: str,
    objects: dict[str, str],
    phys: list[tuple[str, str, str]],
    decl_by_name: dict[str, etree._Element],
    wb: Workbook,
) -> list[Table]:
    by_object: dict[str, Table] = {}
    seen: set[tuple[str, str]] = set()
    for oid, name, datatype in phys:
        caption = objects.get(oid, ds_name)
        key = (caption, name)
        if key in seen:
            continue
        seen.add(key)
        table = by_object.setdefault(caption, Table(name=caption))
        decl = decl_by_name.get(name)
        table.columns.append(
            Column(
                name=name,
                datatype=datatype,
                role=(decl.get("role") if decl is not None else None) or "dimension",
                caption=decl.get("caption") if decl is not None else None,
            )
        )
    # Deterministic table order: by caption.
    return [by_object[k] for k in sorted(by_object)]


def _build_single_table(
    ds_name: str,
    ds_el: etree._Element,
    decl_by_name: dict[str, etree._Element],
    wb: Workbook,
) -> Table:
    """Fallback: no object-graph — one table from declared <column> elements."""
    columns: list[Column] = []
    for name, col_el in decl_by_name.items():
        if _is_object_id(name):
            wb.add_flag(
                item=f"{ds_name}.{name}",
                severity=Severity.INFO,
                reason="Dropped Tableau federation join-key column.",
                stage="parse",
            )
            continue
        if col_el.find("./calculation") is not None:
            continue  # calc -> measure, attached later
        columns.append(
            Column(
                name=name,
                datatype=col_el.get("datatype") or "string",
                role=col_el.get("role") or "dimension",
                caption=col_el.get("caption"),
            )
        )
    return Table(name=ds_name, columns=columns)


def _attach_calculations(
    tables: list[Table],
    decl_by_name: dict[str, etree._Element],
    ds_name: str,
    wb: Workbook,
) -> None:
    if not tables:
        return
    primary = max(tables, key=lambda t: len(t.columns))
    for name, col_el in decl_by_name.items():
        calc_el = col_el.find("./calculation")
        if calc_el is None or not calc_el.get("formula"):
            continue
        if _is_object_id(name):
            continue
        primary.columns.append(
            Column(
                name=name,
                datatype=col_el.get("datatype") or "string",
                role=col_el.get("role") or "measure",
                caption=col_el.get("caption"),
                formula=calc_el.get("formula"),
            )
        )


def _parse_relationships(
    ds_el: etree._Element, objects: dict[str, str], wb: Workbook
) -> None:
    for rel in ds_el.findall(".//relationship"):
        exprs = rel.findall("./expression/expression")
        if len(exprs) != 2:
            continue
        first = rel.find("./first-end-point")
        second = rel.find("./second-end-point")
        if first is None or second is None:
            continue
        from_table = objects.get(_clean_name(first.get("object-id")))
        to_table = objects.get(_clean_name(second.get("object-id")))
        from_col = _clean_name(exprs[0].get("op"))
        to_col = _clean_name(exprs[1].get("op"))
        if not (from_table and to_table and from_col and to_col):
            continue
        wb.relationships.append(
            Relationship(
                from_table=from_table,
                from_column=from_col,
                to_table=to_table,
                to_column=to_col,
                kind="many_to_one",
                datasource_id=ds_el.get("name") or "",
            )
        )
