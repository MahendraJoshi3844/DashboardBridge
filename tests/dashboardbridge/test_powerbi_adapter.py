"""Reading a Power BI project into the canonical model (`P6a.1`, `P6a.3`).

The fixture is **hand-written to look like Power BI Desktop's output, not
ours**. That is the whole point of it. A reader tested against a project our own
emitter produced would prove only that the two agree with each other, and would
pass while being unable to open a single real workbook — so `Retail.SemanticModel`
carries the things Desktop writes and we never do: `lineageTag`, `formatString`,
`summarizeBy`, `isHidden`, `isKey`, `annotation`, `variation`, a hierarchy, a
triple-backtick multi-line measure, an unquoted table name, and a relationship in
its own file.

This is also a third parser for TMDL, and deliberately so. The validator has one
and shares no code with the *writer*, because a check that asks the emitter what
it emitted proves only that the emitter is self-consistent. This one is a
*reader* with different depth — it needs expressions, datatypes, hierarchies and
report bindings, where the validator needs existence and counts. Merging them
would give the validator the reader's blind spots.

`P6a.2` — a DAX expression parser — is not here. Expressions are carried across
verbatim and marked as untranslated, which is the honest state: the model records
what the expression *is*, and nothing yet claims to understand it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboardbridge_contracts.enums import BindingRole, DataType, Grain, Platform
from engines.adapters.powerbi import PowerBIAdapter

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pbip"


@pytest.fixture(scope="module")
def model():
    return PowerBIAdapter().read(FIXTURE)


# --- detection ---------------------------------------------------------------


def test_a_pbip_directory_is_recognised():
    assert PowerBIAdapter().detects(FIXTURE) is True


def test_a_directory_that_is_not_a_project_is_not_claimed(tmp_path):
    """Claiming one would produce an empty model rather than an error."""
    (tmp_path / "notes.txt").write_text("nothing to see", encoding="utf-8")
    assert PowerBIAdapter().detects(tmp_path) is False


def test_a_tableau_workbook_is_not_mistaken_for_a_project(tmp_path):
    (tmp_path / "book.twb").write_text("<workbook/>", encoding="utf-8")
    assert PowerBIAdapter().detects(tmp_path) is False


# --- the semantic model ------------------------------------------------------


def test_the_model_says_which_platform_it_came_from(model):
    assert model.source_platform is Platform.POWERBI


def test_both_tables_are_read_including_the_unquoted_one(model):
    """TMDL quotes a name only when it has to. `table Store` is as valid as
    `table 'Sales'`, and a parser that only handles the quoted form reads half a
    model and reports no error."""
    tables = {table.name for ds in model.datasources for table in ds.tables}
    assert tables == {"Sales", "Store"}


def test_columns_carry_their_datatypes(model):
    columns = _columns(model, "Sales")
    assert columns["Order ID"].datatype is DataType.STRING
    assert columns["Order Date"].datatype is DataType.DATETIME
    assert columns["Revenue"].datatype is DataType.DECIMAL
    assert columns["Units"].datatype is DataType.INTEGER


def test_a_calculated_column_carries_its_expression_and_row_grain(model):
    """`column 'X' = <expression>` is a calculated column: row grain."""
    net = _columns(model, "Sales")["Net Revenue"]
    assert net.expression is not None
    assert net.expression.source_language == "dax"
    assert "Sales[Revenue]" in net.expression.source_text
    assert net.grain is Grain.ROW


def test_a_measure_carries_its_expression_and_aggregate_grain(model):
    total = _columns(model, "Sales")["Total Revenue"]
    assert total.expression is not None
    assert total.expression.source_text == "SUM(Sales[Revenue])"
    assert total.grain is Grain.AGGREGATE


def test_a_multi_line_measure_is_read_whole(model):
    """Desktop writes a long expression in a triple-backtick block.

    Reading only the first line would silently truncate an expression into
    something that still looks like DAX.
    """
    per_unit = _columns(model, "Sales")["Revenue per Unit"].expression
    assert per_unit is not None
    assert "DIVIDE(" in per_unit.source_text
    assert "SUM(Sales[Units])" in per_unit.source_text


def test_nothing_read_is_claimed_to_be_translated(model):
    """`P6a.2` does not exist, so no expression has been understood.

    A `translation` here would be the reader asserting an equivalence nobody
    computed.
    """
    for _, column in _all_columns(model):
        assert column.translation is None


def test_the_relationship_is_read_from_its_own_file(model):
    """Desktop keeps relationships in `relationships.tmdl`, not in the table."""
    assert len(model.relationships) == 1
    relationship = model.relationships[0]
    assert relationship.from_table == "Sales"
    assert relationship.from_column == "Store Key"
    assert relationship.to_table == "Store"
    assert relationship.to_column == "Store Key"


# --- the report --------------------------------------------------------------


def test_the_page_becomes_a_dashboard_with_its_display_name(model):
    assert [dashboard.name for dashboard in model.dashboards] == ["Revenue by Region"]


def test_the_visual_is_read_with_its_type_and_title(model):
    visual = model.visuals[0]
    assert visual.visual_type == "columnChart"
    assert visual.name == "Revenue by Region"


def test_every_projection_becomes_a_binding_with_its_role(model):
    """The well a field sits in is its role: `Category`, `Y`, `Series`."""
    roles = {
        (binding.role, binding.field.column)
        for binding in model.visuals[0].bindings
        if binding.field
    }
    assert (BindingRole.CATEGORY, "Region") in roles
    assert (BindingRole.VALUE, "Total Revenue") in roles
    assert (BindingRole.SERIES, "Store Name") in roles


def test_a_binding_remembers_which_table_it_came_from(model):
    region = next(
        binding
        for binding in model.visuals[0].bindings
        if binding.field and binding.field.column == "Region"
    )
    assert region.field is not None
    assert region.field.table == "Store"


def test_a_report_filter_is_read_as_a_filter_binding(model):
    filters = model.visuals[0].filters
    assert [f.field.column for f in filters if f.field] == ["Order Date"]
    assert all(f.role is BindingRole.FILTER for f in filters)


# --- determinism -------------------------------------------------------------


def test_reading_the_same_project_twice_gives_the_same_model():
    first = PowerBIAdapter().read(FIXTURE)
    second = PowerBIAdapter().read(FIXTURE)
    assert first == second


def _columns(model, table_name: str):
    return {
        column.name: column
        for datasource in model.datasources
        for table in datasource.tables
        if table.name == table_name
        for column in table.columns
    }


def _all_columns(model):
    for datasource in model.datasources:
        for table in datasource.tables:
            for column in table.columns:
                yield table.name, column


# --- against a project we produced ourselves ---------------------------------


def test_it_also_reads_a_project_this_converter_produced(tmp_path):
    """Tableau in, PBIP out, canonical back. As close to a round trip as `P6a`
    reaches before `P6b` exists.

    Kept *separate* from the fixture tests and never a substitute for them. A
    reader exercised only against its own writer's output agrees with itself and
    can still be unable to open a single file Power BI Desktop wrote - which is
    why the fixture is hand-authored and this is the secondary check.
    """
    from engines.t2pbi.pipeline import run

    produced = tmp_path / "out"
    run(
        Path(__file__).resolve().parents[1] / "fixtures" / "clashes.twb",
        produced,
        "Clashes",
    )

    model = PowerBIAdapter().read(produced)

    names = {table.name for ds in model.datasources for table in ds.tables}
    assert {"Orders", "Targets", "Returns"} <= names
    assert model.visuals, "the report's visuals were not read back"
    assert any(
        column.expression
        for _, column in _all_columns(model)
    ), "no translated expression survived the round trip"


def test_reading_back_what_we_wrote_never_claims_a_translation(tmp_path):
    """Our own DAX is still just DAX to a reader.

    The expressions in that project *are* translations - we made them - but this
    adapter did not, and recording one would let a model claim provenance it
    has not got.
    """
    from engines.t2pbi.pipeline import run

    produced = tmp_path / "out"
    run(
        Path(__file__).resolve().parents[1] / "fixtures" / "clashes.twb",
        produced,
        "Clashes",
    )

    model = PowerBIAdapter().read(produced)
    assert all(column.translation is None for _, column in _all_columns(model))
