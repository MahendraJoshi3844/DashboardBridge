from t2pbi.core.parse import _disambiguate_table_names
from t2pbi.ir.model import DataSource, Relationship, Table, Workbook
from t2pbi.core.parse import parse_workbook


def test_parse_datasources(sample_twb_bytes):
    wb = parse_workbook(sample_twb_bytes)
    # Parameters datasource is skipped.
    assert len(wb.datasources) == 1
    ds = wb.datasources[0]
    assert ds.name == "Sales"
    cols = ds.tables[0].columns
    names = {c.name for c in cols}
    assert {"Sales", "Quantity", "Order Date", "Profit Ratio"} <= names

    profit = next(c for c in cols if c.name == "Profit Ratio")
    assert profit.is_calculated
    assert "SUM([Sales])" in profit.formula


def test_parse_worksheets_and_dashboards(sample_twb_bytes):
    wb = parse_workbook(sample_twb_bytes)
    assert wb.version == "2021.4"
    assert len(wb.worksheets) == 1
    ws = wb.worksheets[0]
    assert ws.name == "Sales by Date"
    assert ws.visual_type == "bar"
    assert len(wb.dashboards) == 1
    assert "Sales by Date" in wb.dashboards[0].sheet_names


def test_disambiguation_leaves_another_datasources_relationship_alone():
    """Renaming a colliding table must not repoint the relationship that kept the name.

    `renames` was keyed by the original table name, but the *first* datasource's
    table keeps that name - so rewriting relationships by name moved Sales DS's
    own `Orders -> Customers` onto HR DS's unrelated `Orders`, and
    `relationships.tmdl` described a join the workbook never had.
    """
    wb = Workbook(version="18.1")
    wb.datasources = [
        DataSource(
            name="Sales DS",
            connection="extract",
            source_id="federated.sales",
            tables=[Table(name="Orders"), Table(name="Customers")],
        ),
        DataSource(
            name="HR DS",
            connection="extract",
            source_id="federated.hr",
            tables=[Table(name="Orders")],
        ),
    ]
    # Parsed from Sales DS, so it means Sales DS's own two tables.
    wb.relationships = [
        Relationship(
            "Orders", "CustID", "Customers", "CustID", datasource_id="federated.sales"
        )
    ]

    _disambiguate_table_names(wb)

    # HR DS's table is the one that gets renamed; Sales DS's keeps the name.
    assert [t.name for ds in wb.datasources for t in ds.tables] == [
        "Orders",
        "Customers",
        "HR DS Orders",
    ]
    # ...so the relationship still joins Sales DS's own two tables.
    assert wb.relationships[0].from_table == "Orders"
    assert wb.relationships[0].to_table == "Customers"
