"""The Tableau adapter: engine IR -> canonical contracts.

This is the seam (ADR-008). Everything downstream - the API, the web app, every
future platform - sees only what `normalize` produces, so these tests pin the
mapping rather than the plumbing.
"""

import pytest

from dashboardbridge_contracts import CanonicalModel, Platform
from dashboardbridge_contracts.enums import (
    Aggregation,
    BindingRole,
    ConversionMethod,
    ConversionStatus,
    DataType,
    DatePart,
    Grain,
    Severity,
)
from engines.adapters.tableau import TableauAdapter

ENCODED_TWB = b"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='2021.4'>
  <datasources>
    <datasource name='Parameters'>
      <column name='[Rate]' caption='Rate' datatype='real' param-domain-type='range'
              value='0.5'><range min='0.0' max='1.0' granularity='0.1' /></column>
    </datasource>
    <datasource name='federated.abc' caption='Orders'>
      <connection class='sqlserver' />
      <column name='[Sales]' datatype='real' role='measure' />
      <column name='[Order Date]' datatype='date' role='dimension' />
      <column name='[Ship Date]' datatype='date' role='dimension' />
      <column name='[Ratio]' caption='Ratio' datatype='real' role='measure'>
        <calculation class='tableau' formula='SUM([Sales])/SUM([Sales])' />
      </column>
      <column name='[Days]' caption='Days' datatype='integer' role='measure'>
        <calculation class='tableau' formula="DATEDIFF('day',[Order Date],[Ship Date])" />
      </column>
      <column name='[Forecast]' caption='Forecast' datatype='real' role='measure'>
        <calculation class='tableau' formula='[Sales]*(1+[Parameters].[Rate])' />
      </column>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Sales by Date'>
      <table><view>
        <rows>[federated.abc].[sum:Sales:qk]</rows>
        <cols>[federated.abc].[yr:Order Date:ok]</cols>
      </view>
      <panes><pane><mark class='Bar' /></pane></panes></table>
    </worksheet>
    <worksheet name='Unbindable'>
      <table><view>
        <rows>[federated.abc].[:Measure Names]</rows>
      </view>
      <panes><pane><mark class='Bar' /></pane></panes></table>
    </worksheet>
  </worksheets>
  <dashboards>
    <dashboard name='Overview'><zones><zone name='Sales by Date' /></zones></dashboard>
  </dashboards>
</workbook>
"""


@pytest.fixture
def model() -> CanonicalModel:
    return TableauAdapter().normalize(TableauAdapter().parse(ENCODED_TWB))


# --- detection is cheap and safe on untrusted input ------------------------


def test_detects_a_tableau_workbook():
    assert TableauAdapter().detect(ENCODED_TWB) is True


def test_does_not_claim_unrelated_bytes():
    assert TableauAdapter().detect(b"PK\x03\x04 not a workbook") is False
    assert TableauAdapter().detect(b"") is False


# --- structure -------------------------------------------------------------


def test_the_model_names_its_source_platform(model):
    assert model.source_platform is Platform.TABLEAU
    assert model.source_version == "2021.4"


def test_parameters_are_not_a_datasource(model):
    """Tableau keeps parameters in a pseudo-datasource; the canonical model does
    not, because a parameter is not a table anywhere else."""
    assert [ds.name for ds in model.datasources] == ["Orders"]
    assert [p.caption for p in model.parameters] == ["Rate"]


def test_columns_carry_both_names(model):
    ratio = next(c for c in model.all_columns() if c.name == "Ratio")
    assert ratio.caption == "Ratio"
    assert ratio.display_name == "Ratio"


def test_ids_are_deterministic_name_paths(model):
    """Not random, not timestamped - identical input must produce identical
    output, and an id a human can read is an id they can trace."""
    assert {c.id for c in model.all_columns()} >= {"Orders.Sales", "Orders.Ratio"}


def test_datatypes_are_canonical_not_tableau_spellings(model):
    sales = next(c for c in model.all_columns() if c.name == "Sales")
    assert sales.datatype is DataType.DECIMAL


# --- grain: the property the whole conversion turns on ---------------------


def test_an_aggregated_calc_is_aggregate_grain(model):
    assert next(c for c in model.all_columns() if c.name == "Ratio").grain is Grain.AGGREGATE


def test_a_row_level_calc_is_row_grain(model):
    assert next(c for c in model.all_columns() if c.name == "Days").grain is Grain.ROW


def test_an_ambiguous_calc_has_no_grain_and_is_flagged(model):
    """[Sales]*(1+[Rate]) mixes a row-level column with a parameter. The
    aggregation the author intended is not stated, so we refuse rather than
    guess - and the absence must be visible, not defaulted away."""
    forecast = next(c for c in model.all_columns() if c.name == "Forecast")
    assert forecast.grain is None
    assert any("Forecast" in f.item for f in model.flags)


# --- shelf encoding becomes platform-neutral bindings ----------------------


def test_an_encoded_shelf_ref_becomes_a_binding(model):
    visual = next(v for v in model.visuals if v.name == "Sales by Date")
    value = next(b for b in visual.bindings if b.role is BindingRole.VALUE)
    assert value.field is not None
    assert value.field.column == "Sales"
    assert value.aggregation is Aggregation.SUM


def test_a_date_part_survives_the_mapping(model):
    visual = next(v for v in model.visuals if v.name == "Sales by Date")
    category = next(b for b in visual.bindings if b.role is BindingRole.CATEGORY)
    assert category.date_part is DatePart.YEAR
    assert category.field is not None and category.field.column == "Order Date"


def test_an_unresolvable_construct_is_marked_not_bound(model):
    """':Measure Names' names no real column. Binding it to a guess is the bug
    that once made every visual point at a column that did not exist."""
    visual = next(v for v in model.visuals if v.name == "Unbindable")
    binding = visual.bindings[0]
    assert binding.resolvable is False
    assert binding.field is None
    assert binding.raw


# --- flags carry all three axes -------------------------------------------


def test_flags_record_method_status_and_severity(model):
    flag = next(f for f in model.flags if "Forecast" in f.item)
    assert flag.status is ConversionStatus.AI_REQUIRED
    assert flag.method is ConversionMethod.MANUAL
    assert flag.severity is Severity.MANUAL


def test_nothing_unconvertible_is_dropped_silently(model):
    """Every object that could not be represented must appear in flags."""
    unresolvable = [
        b
        for v in model.visuals
        for b in v.bindings
        if not b.resolvable
    ]
    for binding in unresolvable:
        assert any(binding.raw in f.item or binding.raw in f.reason for f in model.flags)


# --- determinism -----------------------------------------------------------


def test_normalising_twice_produces_an_identical_model():
    adapter = TableauAdapter()
    first = adapter.normalize(adapter.parse(ENCODED_TWB))
    second = adapter.normalize(adapter.parse(ENCODED_TWB))
    assert first.model_dump_json() == second.model_dump_json()


# --- an unreadable workbook must not look like an empty one ----------------

EMPTY_SHELL = b"<?xml version='1.0'?><workbook version='2021.4'></workbook>"


def test_a_workbook_yielding_nothing_is_refused_not_reported_as_empty():
    """A file that parses to zero of everything was almost certainly not read.

    Reporting "0 columns, 0 flags" presents that as an empty workbook, which is
    a silent drop wearing a number: the user sees a confident zero rather than
    "we could not read this".
    """
    from engines.adapters.tableau import UnreadableArtifact

    adapter = TableauAdapter()
    with pytest.raises(UnreadableArtifact):
        adapter.normalize(adapter.parse(EMPTY_SHELL))


def test_a_workbook_with_content_but_no_visuals_is_still_accepted():
    """The guard must catch an unreadable file, not a legitimately sparse one."""
    sparse = b"""<?xml version='1.0'?>
    <workbook version='2021.4'><datasources>
      <datasource name='federated.a' caption='Orders'>
        <connection class='sqlserver' />
        <column name='[Sales]' datatype='real' role='measure' />
      </datasource>
    </datasources></workbook>"""
    adapter = TableauAdapter()
    model = adapter.normalize(adapter.parse(sparse))
    assert len(model.all_columns()) == 1
    assert model.visuals == []
