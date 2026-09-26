"""`P6b.5` - one worksheet cannot span two data sources.

The defect was visible in the golden and in no failing test: `retail.twb` put
`[federated.sales].[sum:Total Revenue:qk]` on rows and
`[federated.store].[none:Region:nk]` on columns. Every canonical table became
its own `<datasource>`, and Tableau binds one worksheet to one data source, so a
Power BI visual whose fields come from two related tables had no correct form.

It was left open in `P6b.3` because the fix is a design decision, not a defect:
emit a join, declare a blend, or refuse. The decision taken is **relate where
the model says the tables are related, and refuse where it does not** - which is
the only one of the three that adds no claim the source model did not make. A
blend would invent a linking field; a join would impose inner/outer semantics
Power BI's relationship never stated.

## Where the shape comes from

Not from inference. `testing_content/Superstore.twb` is a workbook **Tableau
itself wrote**, and it relates Orders, People and Returns exactly this way:

    <connection class='federated'>
      <relation type='collection'>
        <relation name='Orders' table='[Orders$]' type='table' />
        ...
      <cols>
        <map key='[Region]'          value='[Orders].[Region]' />
        <map key='[Region (People)]' value='[People].[Region]' />
    ...
    <object-graph>            <!-- last child of <datasource> -->
      <objects>
        <object caption='Orders' id='Orders_6D2EF74F...'>
          <properties context=''><relation ... /></properties>
      <relationships>
        <relationship>
          <expression op='='>
            <expression op='[Region]' />
            <expression op='[Region (People)]' />
          <first-end-point object-id='Orders_...' />
          <second-end-point object-id='People_...' />

Two facts in there are load-bearing and neither is guessable. Related tables
share **one flat field namespace**, in which a name used by two tables is
disambiguated as `Name (Table)` - and the relationship's own expression is
written in those flat names, not in table-qualified ones. A shelf reference then
names the data source and the flat key, which is why merging sources changes
what a shelf must say.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from lxml import etree

from dashboardbridge_contracts import (
    CanonicalModel,
    Column,
    DataSource,
    Expression,
    FieldRef,
    Relationship,
    Table,
    Visual,
    VisualBinding,
)
from dashboardbridge_contracts.enums import (
    Aggregation,
    BindingRole,
    DataType,
    Grain,
    Platform,
)
from engines.adapters.powerbi import PowerBIAdapter
from engines.adapters.tableau_emit import write_twb

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _write(model: CanonicalModel) -> etree._Element:
    with tempfile.TemporaryDirectory() as scratch:
        text = write_twb(model, scratch).read_text(encoding="utf-8")
    return etree.fromstring(text.encode("utf-8"))


def _column(name: str, datatype: DataType = DataType.STRING) -> Column:
    return Column(id=name, name=name, caption=name, datatype=datatype)


def _model(*, related: bool) -> CanonicalModel:
    """Two tables sharing a column name, related or not.

    `Store Key` is in both on purpose: it is the disambiguation case, and it is
    also the case Superstore has (`Region` in Orders and in People).
    """
    sales = Table(
        id="Sales",
        name="Sales",
        columns=[
            _column("Store Key", DataType.INTEGER),
            _column("Revenue", DataType.DECIMAL),
        ],
    )
    store = Table(
        id="Store",
        name="Store",
        columns=[_column("Store Key", DataType.INTEGER), _column("Region")],
    )
    return CanonicalModel(
        source_platform=Platform.POWERBI,
        name="Retail",
        datasources=[DataSource(id="model", name="model", tables=[sales, store])],
        relationships=(
            [
                Relationship(
                    from_table="Sales",
                    from_column="Store Key",
                    to_table="Store",
                    to_column="Store Key",
                )
            ]
            if related
            else []
        ),
        visuals=[
            Visual(
                id="v1",
                name="Revenue by Region",
                visual_type="bar",
                bindings=[
                    VisualBinding(
                        role=BindingRole.VALUE,
                        field=FieldRef(table="Sales", column="Revenue"),
                        aggregation=Aggregation.SUM,
                    ),
                    VisualBinding(
                        role=BindingRole.CATEGORY,
                        field=FieldRef(table="Store", column="Region"),
                    ),
                ],
            )
        ],
    )


@pytest.fixture(scope="module")
def related() -> etree._Element:
    return _write(_model(related=True))


@pytest.fixture(scope="module")
def unrelated() -> etree._Element:
    return _write(_model(related=False))


def _shelves(root: etree._Element) -> list[str]:
    """Only the worksheet shelves.

    Scoped to `<worksheet>` on purpose: a merged data source now has a `<cols>`
    of its own, and the obvious `.//cols` sweep picks up the field-name map as
    though it were a shelf.
    """
    return [
        element.text
        for element in root.findall(".//worksheet//rows")
        + root.findall(".//worksheet//cols")
        if element.text
    ]


# --- related tables ---------------------------------------------------------------------


def test_related_tables_are_written_as_one_data_source(related):
    sources = related.findall("./datasources/datasource")
    assert len(sources) == 1, [s.get("caption") for s in sources]


def test_the_tables_are_listed_in_a_collection_relation(related):
    """Tableau's own container for several tables in one federated connection."""
    collection = related.find(".//connection/relation[@type='collection']")
    assert collection is not None
    assert [child.get("name") for child in collection] == ["Sales", "Store"]


def test_a_name_used_by_two_tables_is_disambiguated_the_way_tableau_does_it(related):
    """`Store Key` is in both tables. Superstore's `Region (People)` is the
    pattern: the first table keeps the plain name and the later one is suffixed
    with its table, because a flat namespace cannot hold the name twice."""
    maps = {
        element.get("key"): element.get("value")
        for element in related.findall(".//connection/cols/map")
    }
    assert maps["[Store Key]"] == "[Sales].[Store Key]"
    assert maps["[Store Key (Store)]"] == "[Store].[Store Key]"
    assert maps["[Region]"] == "[Store].[Region]"


def test_every_column_is_declared_under_its_flat_key(related):
    """The `<column>` elements and the `<cols>` map have to agree: a column
    declared as `[Store Key]` twice is one of them silently winning."""
    names = [element.get("name") for element in related.findall(".//datasource/column")]
    assert names.count("[Store Key]") == 1
    assert "[Store Key (Store)]" in names


def test_the_object_graph_names_one_object_per_table(related):
    graph = related.find(".//datasource/object-graph")
    assert graph is not None
    assert [o.get("caption") for o in graph.findall("./objects/object")] == [
        "Sales",
        "Store",
    ]


def test_the_relationship_is_written_in_flat_names_between_the_two_objects(related):
    """The expression uses the flat keys, exactly as Superstore's does - not
    `[Sales].[Store Key]`, which is what the `<cols>` map is for."""
    graph = related.find(".//datasource/object-graph")
    relationship = graph.find(".//relationships/relationship")
    assert relationship is not None
    operands = [
        e.get("op") for e in relationship.findall("./expression/expression")
    ]
    assert operands == ["[Store Key]", "[Store Key (Store)]"]

    ids = {o.get("caption"): o.get("id") for o in graph.findall("./objects/object")}
    assert relationship.find("./first-end-point").get("object-id") == ids["Sales"]
    assert relationship.find("./second-end-point").get("object-id") == ids["Store"]


def test_object_ids_are_deterministic_and_tableau_shaped(related):
    """Tableau writes `Orders_<32 hex>`. The shape is copied; the value is
    derived from the table name, because the same model must produce the same
    bytes and Tableau's own value is a random GUID."""
    ids = [
        o.get("id") for o in related.findall(".//object-graph/objects/object")
    ]
    for identifier in ids:
        stem, _, suffix = identifier.rpartition("_")
        assert stem in {"Sales", "Store"}
        assert len(suffix) == 32
        assert set(suffix) <= set("0123456789ABCDEF")
    assert ids == [
        o.get("id") for o in _write(_model(related=True)).findall(
            ".//object-graph/objects/object"
        )
    ]


def test_the_worksheet_now_names_one_source_on_both_shelves(related):
    """The defect this task exists for. Two sources on one worksheet is a
    workbook Tableau cannot bind."""
    shelves = _shelves(related)
    assert len(shelves) == 2
    sources = {token.split("].[", 1)[0] + "]" for token in shelves}
    assert len(sources) == 1, shelves


def test_the_shelf_uses_the_flat_key_when_the_name_was_disambiguated():
    """`Store Key` is on both tables, so the one the shelf wants is
    `[Store Key (Store)]`. Writing the raw column name here binds the visual to
    the *other* table's column - a workbook that opens and shows a different
    number, which is the failure mode this whole namespace exists to prevent.

    The first version of this test asserted on `Region`, which is unique and so
    was unchanged by the bug. Found by writing the raw name and watching
    nothing fail.
    """
    model = _model(related=True)
    model.visuals[0].bindings.append(
        VisualBinding(
            role=BindingRole.CATEGORY,
            field=FieldRef(table="Store", column="Store Key"),
        )
    )
    shelves = " ".join(_shelves(_write(model)))
    assert "[none:Store Key (Store):nk]" in shelves
    assert "[none:Store Key:nk]" not in shelves


# --- unrelated tables -------------------------------------------------------------------


def test_unrelated_tables_stay_separate_sources(unrelated):
    assert len(unrelated.findall("./datasources/datasource")) == 2


def test_a_visual_spanning_unrelated_tables_is_refused_not_written_wrong(unrelated):
    """The other half of the decision. There is no correct form, so nothing is
    written on the shelves - the same choice the Power BI side makes for a
    visual it cannot bind, and the same reason: a workbook that opens and shows
    nothing is worse than one that plainly says what is missing."""
    assert _shelves(unrelated) == []


def test_the_refusal_says_which_tables_and_why(unrelated):
    text = etree.tostring(unrelated, encoding="unicode")
    assert "Sales" in text and "Store" in text
    assert "not related" in text or "no relationship" in text


def test_a_refused_worksheet_still_exists(unrelated):
    """Nothing is ever silently dropped: the worksheet was in the source."""
    assert [w.get("name") for w in unrelated.findall(".//worksheet")] == [
        "Revenue by Region"
    ]


# --- what must not change ---------------------------------------------------------------


def test_a_lone_table_is_written_exactly_as_before(related):
    """A model with one table per component must not grow a collection, a
    `<cols>` map or an object graph. Tableau's own single-table data sources
    have none of those - Superstore has ten plain `<relation type='table'>` and
    one collection - and inventing them would be a change to output that was
    already right.
    """
    root = _write(
        CanonicalModel(
            source_platform=Platform.POWERBI,
            name="Lone",
            datasources=[
                DataSource(
                    id="model",
                    name="model",
                    tables=[
                        Table(
                            id="Sales",
                            name="Sales",
                            columns=[_column("Revenue", DataType.DECIMAL)],
                        )
                    ],
                )
            ],
        )
    )
    connection = root.find(".//connection")
    assert [child.tag for child in connection] == ["relation"]
    assert connection.find("./relation").get("type") == "table"
    assert root.find(".//object-graph") is None


def test_a_calculation_is_rewritten_to_the_flat_key_it_now_needs(related):
    """A formula says `[Store Key]`, and after merging that name may belong to
    the other table. Leaving it alone would silently repoint the calculation at
    a different column - the quietest possible fidelity loss, since the workbook
    opens and the number is simply wrong.
    """
    model = _model(related=True)
    store = model.datasources[0].tables[1]
    store.columns.append(
        Column(
            id="Key Label",
            name="Key Label",
            caption="Key Label",
            datatype=DataType.STRING,
            grain=Grain.ROW,
            expression=Expression(
                source_language="tableau_calc", source_text="STR([Store Key])"
            ),
        )
    )
    root = _write(model)
    formulas = [e.get("formula") for e in root.findall(".//calculation")]
    assert "STR([Store Key (Store)])" in formulas
    assert "STR([Store Key])" not in formulas


# --- the real fixture -------------------------------------------------------------------


def test_the_retail_project_produces_one_source_for_its_related_tables():
    """`Sales` and `Store` are related in the PBIP fixture's
    `relationships.tmdl`, which is what made the golden's split visible."""
    model = PowerBIAdapter().read(FIXTURES / "pbip")
    root = _write(model)
    assert len(root.findall("./datasources/datasource")) == 1
    sources = {token.split("].[", 1)[0] for token in _shelves(root)}
    assert len(sources) == 1, sources


def test_every_shelf_reference_still_decodes(related):
    """The writer and the reader must keep agreeing; a merged source changes
    the token, and a token the reader cannot decode is a visual bound to
    nothing."""
    from t2pbi.core.parse.worksheets import decode_shelf_ref

    for token in _shelves(related):
        decoded = decode_shelf_ref(token)
        assert decoded.resolvable, token
        assert decoded.field
