"""The desktop shell's bridge: the payload shape the page depends on."""

from pathlib import Path

from engines.t2pbi.desktop.shell import Api, web_root

MINIMAL_TWB = b"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='2021.4'>
  <datasources>
    <datasource name='federated.abc' caption='Orders'>
      <connection class='sqlserver' />
      <column name='[Sales]' datatype='real' role='measure' />
    </datasource>
  </datasources>
</workbook>
"""


def test_web_root_points_at_the_built_interface():
    assert web_root().name == "web"
    assert web_root().parent.name == "desktop"


def test_convert_returns_the_payload_the_page_binds_to(tmp_path):
    src = tmp_path / "wb.twb"
    src.write_bytes(MINIMAL_TWB)
    payload = Api().convert(str(src), str(tmp_path / "out"))
    assert set(payload) == {"timeline", "stats", "pbipPath", "reportPath"}
    assert payload["timeline"]["events"]
    assert Path(payload["pbipPath"]).exists()


def test_convert_records_a_timeline_the_stage_can_stream(tmp_path):
    src = tmp_path / "wb.twb"
    src.write_bytes(MINIMAL_TWB)
    events = Api().convert(str(src), str(tmp_path / "out"))["timeline"]["events"]
    assert all(e["outcome"] in {"crossed", "held"} for e in events)


def test_suggest_returns_nothing_before_any_conversion():
    assert Api().suggest_dax("Orders.Anything") is None
