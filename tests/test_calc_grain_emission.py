"""End-to-end: calcs must be emitted at the grain they actually evaluate at."""

from engines.t2pbi.core.emit.tmdl import table_tmdl
from engines.t2pbi.core.parse import parse_workbook
from engines.t2pbi.ir import Severity
from engines.t2pbi.pipeline import _translate_calculations

GRAIN_TWB = b"""<?xml version='1.0' encoding='utf-8' ?>
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
        <calculation class='tableau' formula='SUM([Sales]) / SUM([Sales])' />
      </column>
      <column name='[Days]' caption='Days' datatype='integer' role='measure'>
        <calculation class='tableau' formula="DATEDIFF('day',[Order Date],[Ship Date])" />
      </column>
      <column name='[Forecast]' caption='Forecast' datatype='real' role='measure'>
        <calculation class='tableau' formula='[Sales]*(1+[Parameters].[Rate])' />
      </column>
    </datasource>
  </datasources>
</workbook>
"""


def _converted():
    wb = parse_workbook(GRAIN_TWB)
    _translate_calculations(wb)
    return wb


def test_aggregated_calc_is_emitted_as_a_measure():
    wb = _converted()
    tmdl = table_tmdl(wb.all_tables()[0])
    assert "measure 'Ratio' =" in tmdl


def test_row_level_calc_is_emitted_as_a_calculated_column():
    wb = _converted()
    tmdl = table_tmdl(wb.all_tables()[0])
    assert "column 'Days' =" in tmdl
    assert "measure 'Days'" not in tmdl


def test_ambiguous_grain_calc_is_flagged_and_not_emitted():
    wb = _converted()
    tmdl = table_tmdl(wb.all_tables()[0])
    assert "Forecast" not in tmdl
    manual = [f for f in wb.flags if f.severity == Severity.MANUAL]
    assert any("Forecast" in f.item for f in manual)


def test_no_emitted_measure_wraps_an_aggregation_around_a_measure():
    wb = _converted()
    tmdl = table_tmdl(wb.all_tables()[0])
    for agg in ("SUM([", "AVERAGE([", "MIN([", "MAX([", "DISTINCTCOUNT(["):
        assert agg not in tmdl, f"{agg} aggregates a measure reference"
