"""Federation-aware parsing + emit: object tables, params, relationships.

Locks in the Superstore manual-test fixes for table naming, missing columns,
dropped object-id columns, what-if parameters, and relationships.
"""

import json

from engines.t2pbi.core.parse import parse_workbook
from engines.t2pbi.pipeline import run


def test_objects_become_readable_tables(federated_twb_bytes):
    wb = parse_workbook(federated_twb_bytes)
    names = {t.name for ds in wb.datasources for t in ds.tables}
    assert names == {"Orders", "People"}  # readable captions, not federation ids


def test_object_id_columns_are_dropped(federated_twb_bytes):
    wb = parse_workbook(federated_twb_bytes)
    for table in (t for ds in wb.datasources for t in ds.tables):
        for col in table.columns:
            assert "__tableau_internal_object_id__" not in col.name


def test_columns_attributed_to_correct_object(federated_twb_bytes):
    wb = parse_workbook(federated_twb_bytes)
    tables = {t.name: t for ds in wb.datasources for t in ds.tables}
    orders_cols = {c.name for c in tables["Orders"].columns if not c.is_calculated}
    assert {"Region", "Sales"} <= orders_cols
    assert {c.name for c in tables["People"].columns} == {"Region (People)"}


def test_parameters_parsed(federated_twb_bytes):
    wb = parse_workbook(federated_twb_bytes)
    by_caption = {p.caption: p for p in wb.parameters}
    assert by_caption["Growth"].kind == "range"
    assert by_caption["Growth"].min_value == "0.0"
    assert by_caption["Sort by"].kind == "list"
    assert "\"Names\"" in by_caption["Sort by"].members or "Names" in str(
        by_caption["Sort by"].members
    )


def test_relationships_parsed(federated_twb_bytes):
    wb = parse_workbook(federated_twb_bytes)
    assert len(wb.relationships) == 1
    rel = wb.relationships[0]
    assert (rel.from_table, rel.to_table) == ("Orders", "People")
    assert rel.from_column == "Region"
    assert rel.to_column == "Region (People)"


def test_end_to_end_emits_params_and_relationships(federated_twb_path, tmp_path):
    run(federated_twb_path, tmp_path, "FED")
    model = (tmp_path / "FED.SemanticModel" / "definition" / "model.tmdl").read_text()
    assert "relationship" in model
    assert "ref table 'Growth'" in model  # what-if param table referenced

    tables_dir = tmp_path / "FED.SemanticModel" / "definition" / "tables"
    growth = (tables_dir / "Growth.tmdl").read_text()
    assert "GENERATESERIES(0, 1, 0.01)" in growth
    assert "SELECTEDVALUE('Growth'[Growth], 0.6)" in growth

    sortby = (tables_dir / "Sort by.tmdl").read_text()
    assert '"% asc"' in sortby and "\\%" not in sortby  # escape stripped

    # Forecast calc resolves the parameter to its value measure (no hardcode).
    orders = (tables_dir / "Orders.tmdl").read_text()
    assert "[Growth Value]" in orders
    # No object-id columns leaked into emitted TMDL.
    assert "__tableau_internal_object_id__" not in orders


def test_row_level_calc_mixing_a_parameter_is_refused_not_guessed(federated_twb_path, tmp_path):
    """[Sales]*(1+[Param]) has no stated aggregation; emitting one would be a guess."""
    from engines.t2pbi.ir import Severity

    result = run(federated_twb_path, tmp_path, "FED")
    orders = (
        tmp_path / "FED.SemanticModel" / "definition" / "tables" / "Orders.tmdl"
    ).read_text()
    assert "Row Forecast" not in orders
    manual = [f for f in result.workbook.flags if f.severity == Severity.MANUAL]
    assert any("Row Forecast" in f.item for f in manual)
