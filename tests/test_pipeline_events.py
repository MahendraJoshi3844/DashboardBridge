"""The pipeline records what it did, item by item, for the UI to stream."""

from engines.t2pbi.events import EventSink
from engines.t2pbi.pipeline import run

STREAM_TWB = b"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='2021.4'>
  <datasources>
    <datasource name='Parameters'>
      <column name='[Rate]' caption='Rate' datatype='real' param-domain-type='range'
              value='0.5'><range min='0.0' max='1.0' granularity='0.1' /></column>
    </datasource>
    <datasource name='federated.abc' caption='Orders'>
      <connection class='sqlserver' />
      <column name='[Sales]' datatype='real' role='measure' />
      <column name='[Region]' datatype='string' role='dimension' />
      <column name='[Ratio]' caption='Ratio' datatype='real' role='measure'>
        <calculation class='tableau' formula='SUM([Sales])/SUM([Sales])' />
      </column>
      <column name='[Forecast]' caption='Forecast' datatype='real' role='measure'>
        <calculation class='tableau' formula='[Sales]*(1+[Parameters].[Rate])' />
      </column>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Sales by Region'>
      <table><view>
        <rows>[federated.abc].[sum:Sales:qk]</rows>
        <cols>[federated.abc].[none:Region:nk]</cols>
      </view>
      <panes><pane><mark class='Bar' /></pane></panes></table>
    </worksheet>
  </worksheets>
</workbook>
"""


def _timeline(tmp_path):
    src = tmp_path / "stream.twb"
    src.write_bytes(STREAM_TWB)
    sink = EventSink()
    run(src, tmp_path / "out", "Stream", sink=sink)
    return sink.timeline()


def test_run_records_a_timeline(tmp_path):
    assert _timeline(tmp_path).events


def test_every_column_is_recorded_as_crossing(tmp_path):
    names = {e.name for e in _timeline(tmp_path).crossed() if e.kind == "column"}
    assert {"Sales", "Region"} <= names


def test_a_converted_calc_crosses_with_its_grain(tmp_path):
    calcs = [e for e in _timeline(tmp_path).crossed() if e.kind == "calc"]
    ratio = next(e for e in calcs if e.name == "Ratio")
    # The grain, not Power BI's noun for it. The recording is made by the
    # platform-neutral pipeline (`P2.2`); "measure" is what a Power BI
    # emitter turns an aggregate-grain expression into, and saying it here
    # would put the target's vocabulary in the source's record.
    assert ratio.detail == "aggregate"


def test_an_ambiguous_calc_is_held_with_its_reason(tmp_path):
    held = [e for e in _timeline(tmp_path).held() if e.kind == "calc"]
    forecast = next(e for e in held if e.name == "Forecast")
    assert "aggregation" in forecast.detail.lower()


def test_a_bound_visual_crosses_with_its_powerbi_type(tmp_path):
    visuals = [e for e in _timeline(tmp_path).crossed() if e.kind == "visual"]
    assert any(e.detail == "clusteredBarChart" for e in visuals)


def test_a_parameter_is_recorded(tmp_path):
    params = [e for e in _timeline(tmp_path).crossed() if e.kind == "parameter"]
    assert [e.name for e in params] == ["Rate"]


def test_events_carry_an_ir_reference_for_drill_down(tmp_path):
    calc = next(e for e in _timeline(tmp_path).events if e.kind == "calc")
    assert calc.ref  # e.g. "Orders.Ratio"


def test_running_without_a_sink_still_works(tmp_path):
    src = tmp_path / "stream.twb"
    src.write_bytes(STREAM_TWB)
    assert run(src, tmp_path / "out2", "Stream").stats["tables"] == 1
