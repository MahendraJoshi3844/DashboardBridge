"""Worksheet shelves must bind visuals to real columns, or flag and bind nothing.

Guessing a table for an unresolved shelf field produces a visual that silently
points at the wrong data, which is worse than an empty well plus a flag.
"""

from t2pbi.core.mapping import map_visuals
from t2pbi.core.parse import parse_workbook
from t2pbi.ir import CATEGORY, Severity, VALUE

ENCODED_TWB = b"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='2021.4'>
  <datasources>
    <datasource name='federated.abc' caption='Sales'>
      <connection class='sqlserver' />
      <column name='[Order Date]' datatype='date' role='dimension' />
      <column name='[Sales]' datatype='real' role='measure' />
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
        <cols>[federated.abc].[Multiple Values]</cols>
      </view>
      <panes><pane><mark class='Bar' /></pane></panes></table>
    </worksheet>
  </worksheets>
</workbook>
"""


def _workbook():
    return parse_workbook(ENCODED_TWB)


def test_encoded_shelf_fields_decode_to_real_column_names():
    wb = _workbook()
    sheet = wb.worksheets[0]
    # Roles, not shelves (`P2.2`): rows are the values, columns the
    # categories, and the model carries the answer rather than the geometry.
    assert [b.field for b in sheet.placed(VALUE)] == ["Sales"]
    assert [b.field for b in sheet.placed(CATEGORY)] == ["Order Date"]


def test_resolvable_field_binds_to_its_owning_table():
    wb = _workbook()
    visual = map_visuals(wb)[0]
    assert [(f.table, f.column) for f in visual.values] == [("Sales", "Sales")]
    assert [(f.table, f.column) for f in visual.category] == [("Sales", "Order Date")]


def test_unresolvable_shelf_field_is_flagged_and_not_bound():
    wb = _workbook()
    visual = map_visuals(wb)[1]
    assert visual.values == []
    assert visual.category == []
    reasons = [f.reason for f in wb.flags if f.severity == Severity.MANUAL]
    assert any("Measure Names" in r for r in reasons)


def test_no_field_is_ever_assigned_to_a_guessed_table():
    wb = _workbook()
    map_visuals(wb)
    assert not any("assumed table" in f.reason for f in wb.flags)


TWO_SOURCE_TWB = b"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='2021.4'>
  <datasources>
    <datasource name='federated.aaa' caption='Budget'>
      <connection class='excel-direct' />
      <column name='[Sales]' datatype='real' role='measure' />
    </datasource>
    <datasource name='federated.bbb' caption='Actuals'>
      <connection class='sqlserver' />
      <column name='[Sales]' datatype='real' role='measure' />
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Actual Sales'>
      <table><view>
        <rows>[federated.bbb].[sum:Sales:qk]</rows>
      </view>
      <panes><pane><mark class='Bar' /></pane></panes></table>
    </worksheet>
  </worksheets>
</workbook>
"""


def test_field_binds_to_the_datasource_the_shelf_names():
    wb = parse_workbook(TWO_SOURCE_TWB)
    visual = map_visuals(wb)[0]
    # 'Sales' exists in both datasources; the shelf names federated.bbb (Actuals).
    assert [(f.table, f.column) for f in visual.values] == [("Actuals", "Sales")]
