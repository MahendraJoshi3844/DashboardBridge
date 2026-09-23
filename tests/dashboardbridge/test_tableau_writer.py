"""Writing a `.twb` from the canonical model (`P6b.1`, `P6b.4`).

**No Tableau Desktop has ever opened one of these.** The phase's acceptance
criterion — "a generated `.twb` opens in Tableau Desktop without repair" — is
unmet and cannot be met on a machine without Tableau, exactly as the Power BI
Desktop test is unmet on the other side. Everything below is the strongest
evidence available short of that, and is not a substitute for it.

A round trip that *starts from a real workbook* — real `.twb` → canonical →
generated `.twb` → canonical — is what evidence there is, and it is weaker than
it sounds. **The reader is lenient about exactly what the writer must get
right.** `decode_shelf_ref` accepts a bare `[Sales]` as a plain field name,
because older workbooks really do write that, so a round trip passes whether or
not the shelf encoding is correct. A lenient reader cannot validate a strict
writer.

That was found by breaking the writer to see which tests noticed: writing plain
field names failed exactly one test, and it was not a round-trip one. So the
round trip is kept for what it does prove — that tables, columns, calculations
and worksheets survive — and the shelf encoding is asserted *directly*, because
nothing else will catch it.

The trap this generator exists to avoid is the mirror of the parser's costliest
one: Tableau does not put plain field names on a shelf. It writes
`[federated.x].[sum:Sales:qk]`, and a generator that writes `[Sales]` produces a
workbook whose every visual binds to nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from engines.adapters.tableau import TableauAdapter
from engines.adapters.tableau_emit import write_twb

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _canonical(path: Path):
    adapter = TableauAdapter()
    return adapter.normalize(adapter.parse(path.read_bytes()))


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    """Superstore, written back out as a `.twb`."""
    model = _canonical(FIXTURES / "clashes.twb")
    out = tmp_path_factory.mktemp("twb")
    return write_twb(model, out), model


# --- the document -------------------------------------------------------------


def test_the_result_is_well_formed_xml(written):
    path, _ = written
    root = etree.fromstring(path.read_bytes())
    assert root.tag == "workbook"


def test_it_declares_a_version_because_tableau_refuses_a_file_without_one(written):
    path, _ = written
    root = etree.fromstring(path.read_bytes())
    assert root.get("version")


def test_every_table_becomes_a_datasource(written):
    path, model = written
    root = etree.fromstring(path.read_bytes())
    captions = {
        element.get("caption") for element in root.findall("./datasources/datasource")
    }
    assert captions == {table.name for table in model.all_tables()}


def test_a_name_from_the_model_cannot_become_markup(tmp_path):
    """Names come from a file we did not write, and this writes them into XML.

    The same rule the HTML report follows: everything interpolated is escaped by
    the writer, never by the caller remembering to.
    """
    from dashboardbridge_contracts import CanonicalModel, Column, DataSource, Table
    from dashboardbridge_contracts.enums import Platform

    hostile = '</column><script>alert("x")</script>'
    model = CanonicalModel(
        source_platform=Platform.TABLEAU,
        datasources=[
            DataSource(
                id="ds",
                name="ds",
                tables=[
                    Table(
                        id="T",
                        name="T",
                        columns=[Column(id=f"T.{hostile}", name=hostile)],
                    )
                ],
            )
        ],
    )

    path = write_twb(model, tmp_path)

    root = etree.fromstring(path.read_bytes())  # would raise if it broke the document
    assert root.tag == "workbook"
    assert "<script>" not in path.read_text(encoding="utf-8")


# --- shelves ------------------------------------------------------------------


def test_a_shelf_reference_is_written_in_tableau_s_own_encoding(written):
    """The mirror of the parser's costliest trap.

    A shelf holding `[Sales]` binds to nothing. Tableau writes
    `[datasource].[aggregation:Field:kind]`, and so must this.
    """
    path, _ = written
    root = etree.fromstring(path.read_bytes())
    shelves = [
        element.text
        for element in root.findall(".//rows") + root.findall(".//cols")
        if element.text
    ]
    assert shelves, "no worksheet wrote a shelf at all"
    for token in shelves:
        assert token.startswith("["), token
        inner = token.split("].[", 1)[-1].rstrip("]")
        assert inner.count(":") == 2, f"{token!r} is not an encoded shelf reference"


def test_a_shelf_reference_survives_being_read_back(written):
    """Necessary, and on its own not sufficient.

    The parser accepts a bare `[Sales]` too - older workbooks write them - so
    this passes for an encoding that would bind nothing in Desktop. The test
    above is the one that would fail; this one only rules out a token so
    malformed that even a lenient reader gives up.
    """
    from engines.t2pbi.core.parse.worksheets import decode_shelf_ref

    path, _ = written
    root = etree.fromstring(path.read_bytes())
    for element in root.findall(".//rows") + root.findall(".//cols"):
        if not element.text:
            continue
        decoded = decode_shelf_ref(element.text)
        assert decoded.resolvable, f"{element.text!r} decoded as unresolvable"
        assert decoded.field


# --- the round trip -----------------------------------------------------------


def test_the_structure_survives_a_round_trip(written, tmp_path):
    """Tableau → canonical → `.twb` → canonical, starting from a real workbook."""
    path, original = written
    again = _canonical(path)

    assert {t.name for t in again.all_tables()} == {
        t.name for t in original.all_tables()
    }
    assert {c.id for c in again.all_columns()} == {c.id for c in original.all_columns()}


def test_calculations_survive_a_round_trip_verbatim(written):
    """A Tableau formula written back out is the same formula.

    Nothing translates here: the canonical model already holds the source
    expression, and rewriting it would be a translation nobody asked for.
    """
    path, original = written
    again = _canonical(path)

    before = {
        column.id: column.expression.source_text
        for column in original.all_columns()
        if column.expression
    }
    after = {
        column.id: column.expression.source_text
        for column in again.all_columns()
        if column.expression
    }
    assert after == before


def test_worksheets_survive_a_round_trip(written):
    path, original = written
    again = _canonical(path)
    assert {v.name for v in again.visuals} == {v.name for v in original.visuals}


def test_writing_the_same_model_twice_produces_the_same_bytes(tmp_path):
    """Determinism, on a file a person may diff between two runs."""
    model = _canonical(FIXTURES / "clashes.twb")
    first = write_twb(model, tmp_path / "a").read_bytes()
    second = write_twb(model, tmp_path / "b").read_bytes()
    assert first == second


# --- what it refuses to invent -------------------------------------------------


def _one_column_model(expression_text: str, language: str = "dax"):
    from dashboardbridge_contracts import (
        CanonicalModel,
        Column,
        DataSource,
        Expression,
        Table,
    )
    from dashboardbridge_contracts.enums import Platform

    return CanonicalModel(
        source_platform=Platform.POWERBI,
        datasources=[
            DataSource(
                id="ds",
                name="Sales",
                tables=[
                    Table(
                        id="Sales",
                        name="Sales",
                        columns=[
                            Column(
                                id="Sales.Total",
                                name="Total",
                                expression=Expression(
                                    source_language=language,
                                    source_text=expression_text,
                                ),
                            )
                        ],
                    )
                ],
            )
        ],
    )


def test_a_translatable_dax_expression_is_written_as_a_tableau_formula(tmp_path):
    """`P6b.2` is what changed here.

    Before it existed, every expression that came from Power BI was left out of
    the workbook. Now the ones a rule pack can translate are carried across, and
    only the ones it refuses are left out.
    """
    path = write_twb(_one_column_model("AVERAGE(Sales[Revenue])"), tmp_path)
    root = etree.fromstring(path.read_bytes())

    calculation = root.find(".//calculation")
    assert calculation is not None
    assert calculation.get("formula") == "AVG([Revenue])"
    assert calculation.get("class") == "tableau"


def test_an_untranslatable_dax_expression_is_still_not_written_as_a_formula(tmp_path):
    """Writing it into a `formula` attribute would produce a workbook that opens
    and then fails on every row, which is worse than a field that is plainly
    absent."""
    path = write_twb(_one_column_model("CALCULATE(SUM(Sales[Revenue]))"), tmp_path)
    text = path.read_text(encoding="utf-8")

    # The reason names the construct, so the word itself is expected in the
    # file. What must not be there is the expression, as a formula.
    assert "CALCULATE(SUM(Sales[Revenue]))" not in text
    assert "<calculation" not in text


def test_what_could_not_be_carried_is_written_into_the_file_that_lacks_it(tmp_path):
    """Absent is not the same as silently absent.

    The workbook is the only artifact the person opening it has, so the reason
    the field has no formula is recorded beside the field rather than only in a
    report they may never see.
    """
    path = write_twb(_one_column_model("CALCULATE(SUM(Sales[Revenue]))"), tmp_path)
    text = path.read_text(encoding="utf-8")

    assert "not carried" in text
    assert "filter context" in text
    # An XML comment cannot contain a double hyphen, and a refusal reason may.
    etree.fromstring(path.read_bytes())


def test_a_tableau_expression_is_still_written_verbatim_without_translation(tmp_path):
    """Nothing translates a Tableau formula: the model already holds it, and
    rewriting it would be a translation nobody asked for."""
    path = write_twb(
        _one_column_model("IF [Sales] > 0 THEN 1 ELSE 0 END", language="tableau_calc"),
        tmp_path,
    )
    root = etree.fromstring(path.read_bytes())
    assert root.find(".//calculation").get("formula") == "IF [Sales] > 0 THEN 1 ELSE 0 END"


# --- role and type -------------------------------------------------------------
#
# Found by reading the golden output rather than by a failing test: `Total
# Revenue = SUM([Revenue])` was written as a string dimension. The writer was
# deriving the role from the datatype and ignoring the grain, which is the one
# fact the model actually records about it.


def _lone_source(table):
    """The one-table data source `_column` is written against here.

    `P6b.5` gave `_column` a `_Source`, because related tables share one flat
    field namespace and the column's declared name comes from it. These tests
    are about role and datatype, so the source is the trivial one.
    """
    from engines.adapters.tableau_emit import _Source, _flat_keys

    return _Source(
        id="federated.t",
        caption=table.name,
        tables=(table,),
        keys=_flat_keys((table,)),
    )


def test_an_aggregate_calculation_is_written_as_a_measure_not_a_dimension():
    """Grain is recorded; role was being guessed from the datatype instead.

    A measure written as a nominal string dimension contradicts the formula
    beside it: Tableau would offer `SUM([Revenue])` as a discrete field to slice
    by, which is not a thing it can be.
    """
    from dashboardbridge_contracts.enums import Grain

    from engines.adapters.tableau_emit import _column
    from dashboardbridge_contracts import Column, Table

    column = Column(id="T.Total", name="Total", grain=Grain.AGGREGATE)
    table = Table(id="T", name="T")
    written = " ".join(_column(column, table, _lone_source(table)))

    assert 'role="measure"' in written
    assert 'type="quantitative"' in written


def test_an_aggregate_of_unknown_type_is_written_as_a_number_and_says_so():
    """The writer's one assumption, stated rather than hidden.

    TMDL gives a measure no dataType - Power BI infers it - and Tableau requires
    one. `string` is as much a claim as `real` and a worse one, because it
    contradicts the aggregate role the same column carries. So `real` is
    written, and the assumption is named here so that it is reviewed rather
    than inherited.
    """
    from dashboardbridge_contracts.enums import DataType, Grain

    from engines.adapters.tableau_emit import _column
    from dashboardbridge_contracts import Column, Table

    column = Column(
        id="T.Total", name="Total", datatype=DataType.UNKNOWN, grain=Grain.AGGREGATE
    )
    table = Table(id="T", name="T")
    written = " ".join(_column(column, table, _lone_source(table)))

    assert 'datatype="real"' in written


def test_a_row_level_column_still_takes_its_role_from_its_datatype():
    """Tableau's own default when it connects to a table: numeric fields become
    measures, everything else a dimension. Nothing better is recorded, and
    matching the target tool's behaviour is not a guess about the source."""
    from dashboardbridge_contracts.enums import DataType

    from engines.adapters.tableau_emit import _column
    from dashboardbridge_contracts import Column, Table

    text = Column(id="T.Name", name="Name", datatype=DataType.STRING)
    number = Column(id="T.Units", name="Units", datatype=DataType.INTEGER)
    table = Table(id="T", name="T")

    table = Table(id="T", name="T", columns=[text, number])
    source = _lone_source(table)

    assert 'role="dimension"' in " ".join(_column(text, table, source))
    assert 'role="measure"' in " ".join(_column(number, table, source))
