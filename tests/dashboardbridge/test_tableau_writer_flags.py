"""What the `.twb` writer did not carry across, reported as flags.

`SPEC-powerbi-to-tableau-web.md` FR5 and AC3. The writer used to record a
refusal only as an XML comment inside the produced workbook. A person using the
web application never opens that file in a text editor, so a comment is a
refusal nobody reads, and "nothing dropped silently" was true of the file and
untrue of the product.

Worse, several things were dropped with no trace at all: parameters, visual
filters, bindings in wells the writer does not place, and the layout of every
dashboard. Each of those now raises a flag.

The comment and the flag are built from the same record, so they cannot
disagree. `test_every_comment_has_a_flag` counts both on real output and fails
if a future refusal is written in only one of the two places.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from dashboardbridge_contracts import (
    CanonicalModel,
    Column,
    Dashboard,
    DataSource,
    Expression,
    FieldRef,
    Parameter,
    Table,
    Visual,
    VisualBinding,
)
from dashboardbridge_contracts.enums import (
    BindingRole,
    ConversionStatus,
    DataType,
    Grain,
    Platform,
    Stage,
)
from lxml import etree

pytest.importorskip("t2pbi", reason="optional engine not installed on this deployment")

from engines.adapters.powerbi import PowerBIAdapter
from engines.adapters.tableau import TableauAdapter
from engines.adapters.tableau_emit import emit_twb, write_twb

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_COMMENT = re.compile(r"<!-- not carried: (.*?) -->")


def _from_tableau(name: str) -> CanonicalModel:
    adapter = TableauAdapter()
    return adapter.normalize(adapter.parse((FIXTURES / name).read_bytes()))


def _from_powerbi() -> CanonicalModel:
    return PowerBIAdapter().read(FIXTURES / "pbip")


def _model(**overrides) -> CanonicalModel:
    """One table, `Sales`, with a physical and a DAX-calculated column."""
    sales = Table(
        id="Sales",
        name="Sales",
        columns=[
            Column(id="Sales.Region", name="Region", datatype=DataType.STRING, grain=Grain.ROW),
            Column(id="Sales.Revenue", name="Revenue", datatype=DataType.DECIMAL, grain=Grain.ROW),
        ],
    )
    fields = {
        "source_platform": Platform.POWERBI,
        "name": "Test",
        "datasources": [DataSource(id="model", name="Test", tables=[sales])],
    }
    fields.update(overrides)
    return CanonicalModel(**fields)


def _binding(role: BindingRole, column: str, table: str = "Sales") -> VisualBinding:
    return VisualBinding(role=role, field=FieldRef(table=table, column=column))


def _flags_for(model: CanonicalModel, tmp_path: Path, item: str):
    emission = emit_twb(model, tmp_path)
    return [flag for flag in emission.flags if flag.item == item]


# --- the comment and the flag agree --------------------------------------------


@pytest.mark.parametrize("source", ["powerbi", "clashes"])
def test_every_comment_has_a_flag(source, tmp_path):
    model = _from_powerbi() if source == "powerbi" else _from_tableau("clashes.twb")
    emission = emit_twb(model, tmp_path)
    comments = _COMMENT.findall(emission.path.read_text(encoding="utf-8"))

    assert comments, "the fixture was chosen because it has a refusal; it no longer does"
    flagged = [flag.reason for flag in emission.flags]
    for comment in comments:
        assert comment in flagged, f"refusal written to the file but not reported: {comment}"


def test_write_twb_still_returns_the_path_it_always_did(tmp_path):
    """Existing callers, `TableauAdapter.generate` among them, are unaffected."""
    path = write_twb(_model(), tmp_path)
    assert isinstance(path, Path) and path.suffix == ".twb"


def test_emission_is_deterministic(tmp_path):
    model = _from_powerbi()
    first = emit_twb(model, tmp_path / "a")
    second = emit_twb(model, tmp_path / "b")
    assert first.path.read_bytes() == second.path.read_bytes()
    assert first.flags == second.flags


# --- refused expressions --------------------------------------------------------


def test_a_refused_measure_is_held_for_a_person(tmp_path):
    model = _from_powerbi()
    held = [
        flag
        for flag in emit_twb(model, tmp_path).flags
        if flag.stage is Stage.TRANSLATE
    ]
    assert held, "the Retail fixture has a DIVIDE measure that has no rule"
    for flag in held:
        assert flag.status is ConversionStatus.UNSUPPORTED
        assert flag.reason


# --- what used to vanish without a trace ----------------------------------------


def test_a_parameter_is_reported_because_none_are_written(tmp_path):
    model = _model(
        parameters=[Parameter(id="Discount", name="Discount", caption="Discount")]
    )
    xml = emit_twb(model, tmp_path).path.read_text(encoding="utf-8")
    assert "Discount" not in xml, "if parameters are now written, this flag is wrong"

    flags = _flags_for(model, tmp_path, "Discount")
    assert len(flags) == 1
    assert flags[0].status is ConversionStatus.UNSUPPORTED
    assert "parameter" in flags[0].reason.lower()


def test_a_visual_filter_is_reported_because_none_are_written(tmp_path):
    visual = Visual(
        id="v1",
        name="By Region",
        visual_type="clusteredBarChart",
        bindings=[
            _binding(BindingRole.CATEGORY, "Region"),
            _binding(BindingRole.VALUE, "Revenue"),
        ],
        filters=[_binding(BindingRole.FILTER, "Region")],
    )
    flags = _flags_for(_model(visuals=[visual]), tmp_path, "By Region")
    assert any("filter" in flag.reason.lower() for flag in flags)
    assert all(flag.status is ConversionStatus.PARTIAL for flag in flags)


def test_a_field_in_a_well_the_writer_does_not_place_is_named(tmp_path):
    visual = Visual(
        id="v1",
        name="By Region",
        visual_type="clusteredBarChart",
        bindings=[
            _binding(BindingRole.CATEGORY, "Region"),
            _binding(BindingRole.VALUE, "Revenue"),
            _binding(BindingRole.TOOLTIP, "Revenue"),
        ],
    )
    flags = _flags_for(_model(visuals=[visual]), tmp_path, "By Region")
    assert len(flags) == 1
    assert "tooltip" in flags[0].reason.lower()
    assert "Revenue" in flags[0].reason


def test_a_field_whose_table_is_not_in_the_model_is_named(tmp_path):
    visual = Visual(
        id="v1",
        name="By Region",
        visual_type="clusteredBarChart",
        bindings=[
            _binding(BindingRole.CATEGORY, "Region"),
            _binding(BindingRole.VALUE, "Margin", table="Ghost"),
        ],
    )
    flags = _flags_for(_model(visuals=[visual]), tmp_path, "By Region")
    assert len(flags) == 1
    assert "Margin" in flags[0].reason


def test_a_visual_type_with_no_mark_is_named(tmp_path):
    visual = Visual(
        id="v1",
        name="Funnel",
        visual_type="funnel",
        bindings=[_binding(BindingRole.CATEGORY, "Region")],
    )
    flags = _flags_for(_model(visuals=[visual]), tmp_path, "Funnel")
    assert len(flags) == 1
    assert "funnel" in flags[0].reason
    assert flags[0].status is ConversionStatus.PARTIAL


def test_a_cleanly_written_visual_raises_nothing(tmp_path):
    visual = Visual(
        id="v1",
        name="By Region",
        visual_type="clusteredBarChart",
        bindings=[
            _binding(BindingRole.CATEGORY, "Region"),
            _binding(BindingRole.VALUE, "Revenue"),
        ],
    )
    assert _flags_for(_model(visuals=[visual]), tmp_path, "By Region") == []


# --- dashboards -----------------------------------------------------------------


def _dashboard_model() -> CanonicalModel:
    visual = Visual(
        id="a1b2c3",
        name="Revenue by Region",
        visual_type="clusteredBarChart",
        bindings=[
            _binding(BindingRole.CATEGORY, "Region"),
            _binding(BindingRole.VALUE, "Revenue"),
        ],
    )
    return _model(
        visuals=[visual],
        dashboards=[Dashboard(id="p1", name="Overview", visual_ids=["a1b2c3", "gone"])],
    )


def test_a_dashboard_zone_names_the_worksheet_not_the_visual_id(tmp_path):
    """A zone names a worksheet. Power BI visual ids are not worksheet names.

    Found in `golden/retail.twb`: the zone said `v1` and the worksheet was
    called `Revenue by Region`, so the dashboard would have opened empty.
    """
    path = emit_twb(_dashboard_model(), tmp_path).path
    root = etree.fromstring(path.read_bytes())
    worksheets = {node.get("name") for node in root.findall("./worksheets/worksheet")}
    zones = [node.get("name") for node in root.findall("./dashboards/dashboard/zones/zone")]
    assert zones == ["Revenue by Region"]
    assert set(zones) <= worksheets


def test_a_dashboard_is_partial_because_its_layout_is_not_carried(tmp_path):
    flags = _flags_for(_dashboard_model(), tmp_path, "Overview")
    assert any("layout" in flag.reason.lower() for flag in flags)
    assert all(flag.status is ConversionStatus.PARTIAL for flag in flags)


def test_a_zone_for_a_visual_that_does_not_exist_is_reported(tmp_path):
    flags = _flags_for(_dashboard_model(), tmp_path, "Overview")
    assert any("gone" in flag.reason for flag in flags)


# --- assumptions the writer makes are stated, not hidden ------------------------


def test_a_measure_with_no_type_is_written_as_real_and_says_so(tmp_path):
    """TMDL gives a measure no dataType; Tableau requires one (`P6b.3`)."""
    measure = Column(
        id="Sales.Total",
        name="Total",
        grain=Grain.AGGREGATE,
        expression=Expression(source_language="dax", source_text="SUM(Sales[Revenue])"),
    )
    sales = Table(id="Sales", name="Sales", columns=[measure])
    model = _model(datasources=[DataSource(id="model", name="Test", tables=[sales])])
    flags = _flags_for(model, tmp_path, "Sales.Total")
    assumed = [flag for flag in flags if "real" in flag.reason]
    assert len(assumed) == 1
    assert assumed[0].status is ConversionStatus.CONVERTED


def test_a_field_renamed_to_share_a_data_source_says_so(tmp_path):
    """Related tables share one flat namespace; a clash is renamed `Name (Table)`."""
    from dashboardbridge_contracts import Relationship

    orders = Table(
        id="Orders",
        name="Orders",
        columns=[Column(id="Orders.Region", name="Region", datatype=DataType.STRING)],
    )
    people = Table(
        id="People",
        name="People",
        columns=[Column(id="People.Region", name="Region", datatype=DataType.STRING)],
    )
    model = _model(
        datasources=[DataSource(id="model", name="Test", tables=[orders, people])],
        relationships=[
            Relationship(from_table="Orders", from_column="Region", to_table="People", to_column="Region")
        ],
    )
    flags = _flags_for(model, tmp_path, "People.Region")
    assert len(flags) == 1
    assert "Region (People)" in flags[0].reason
    assert flags[0].status is ConversionStatus.CONVERTED
