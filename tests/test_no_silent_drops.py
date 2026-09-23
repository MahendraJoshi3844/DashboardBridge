"""Nothing converts silently wrong, and nothing is dropped without a flag.

The migration report is the product's trust contract: if an item did not make it
across intact, a human has to be able to see that from the report alone.
"""

from engines.t2pbi.core.parse import parse_workbook
from engines.t2pbi.ir import Severity
from engines.t2pbi.pipeline import _translate_calculations, run

DROPS_TWB = b"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='2021.4'>
  <datasources>
    <datasource name='federated.abc' caption='Orders'>
      <connection class='sqlserver' />
      <column name='[Sales]' datatype='real' role='measure' />
      <column name='[Region]' datatype='string' role='dimension' />
      <column name='[Ranked]' caption='Ranked' datatype='real' role='measure'>
        <calculation class='tableau' formula='INDEX()' />
      </column>
      <column name='[Uses Ranked]' caption='Uses Ranked' datatype='real' role='measure'>
        <calculation class='tableau' formula='SUM([Sales]) / [Ranked]' />
      </column>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Auto Sheet'>
      <table><view>
        <rows>[federated.abc].[sum:Sales:qk]</rows>
        <filter class='categorical' column='[federated.abc].[none:Region:nk]' />
      </view>
      <panes><pane><mark class='Automatic' /></pane></panes></table>
    </worksheet>
  </worksheets>
  <dashboards>
    <dashboard name='Exec Overview'>
      <zones><zone name='Auto Sheet' /></zones>
    </dashboard>
  </dashboards>
</workbook>
"""

DUPLICATE_TABLES_TWB = b"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='2021.4'>
  <datasources>
    <datasource name='federated.aaa' caption='Shared'>
      <connection class='excel-direct' />
      <column name='[Amount]' datatype='real' role='measure' />
    </datasource>
    <datasource name='federated.bbb' caption='Shared'>
      <connection class='sqlserver' />
      <column name='[Other]' datatype='real' role='measure' />
    </datasource>
  </datasources>
</workbook>
"""


def _reasons(wb, severity=None):
    return [
        f"{f.item} {f.reason}"
        for f in wb.flags
        if severity is None or f.severity == severity
    ]


def test_automatic_mark_is_flagged_rather_than_silently_called_a_bar_chart():
    wb = parse_workbook(DROPS_TWB)
    assert any(
        "Automatic" in r and "verify" in r.lower() for r in _reasons(wb)
    ), "Tableau's Automatic mark picks a shape at render time; assuming bar is a guess"


def test_dashboard_layout_is_reported_as_not_carried_over(tmp_path):
    result = run_workbook(tmp_path)
    assert any("Exec Overview" in r for r in _reasons(result.workbook))


def test_worksheet_filter_is_reported_as_not_carried_over(tmp_path):
    result = run_workbook(tmp_path)
    assert any("Region" in r and "filter" in r.lower() for r in _reasons(result.workbook))


def test_calc_referencing_a_failed_calc_is_refused_not_left_dangling():
    wb = parse_workbook(DROPS_TWB)
    _translate_calculations(wb)
    by_name = {c.display_name: c for t in wb.all_tables() for c in t.columns}
    assert by_name["Ranked"].dax is None  # INDEX() is unsupported
    assert by_name["Uses Ranked"].dax is None, "would reference a measure that is never emitted"
    assert any("Uses Ranked" in r for r in _reasons(wb, Severity.MANUAL))


def test_same_named_tables_in_two_datasources_do_not_collide(tmp_path):
    from engines.t2pbi.core.emit import write_pbip

    wb = parse_workbook(DUPLICATE_TABLES_TWB)
    write_pbip(wb, tmp_path, "DUP")
    names = {t.name for t in wb.all_tables()}
    assert len(names) == 2, "one table would silently overwrite the other's TMDL file"


def run_workbook(tmp_path):
    src = tmp_path / "drops.twb"
    src.write_bytes(DROPS_TWB)
    return run(src, tmp_path / "out", "Drops")


def test_every_field_placed_on_a_visual_is_bound_or_reported():
    """The rule the colour shelf was quietly breaking (`P2.2`).

    Before this, the parser read only the rows and columns shelves. A field
    dragged onto colour, size, text or tooltip was not converted, not reported,
    and not counted - it simply was not there, which is indistinguishable from a
    worksheet that never had one. Superstore alone carries 31 of them.

    They are still not bound: which Power BI well a Tableau colour encoding
    belongs in is a mapping decision that has not been made, and a well filled
    on a guess is the visual this project refuses to emit. But every one is now
    in the model and every unbound one is in the flags.
    """
    from pathlib import Path
    import tempfile

    from engines.t2pbi.core.mapping import map_visuals
    from engines.t2pbi.core.parse import parse_workbook
    from engines.t2pbi.ir import CATEGORY, VALUE

    workbook = parse_workbook(
        (Path(__file__).parent / "fixtures" / "shelves.twb").read_bytes()
    )
    visuals = map_visuals(workbook)
    bound = {
        (visual.name, ref.column)
        for visual in visuals
        for ref in list(visual.category) + list(visual.values) + list(visual.legend)
    }
    reported = {flag.item for flag in workbook.flags}

    for sheet in workbook.worksheets:
        for binding in sheet.bindings:
            accounted = (sheet.name, binding.field) in bound or any(
                binding.field in item for item in reported
            )
            assert accounted, (
                f"{sheet.name}'s {binding.role} field {binding.field!r} was "
                "neither bound into a visual nor reported"
            )


def test_a_colour_shelf_is_read_rather_than_ignored():
    from pathlib import Path

    from engines.t2pbi.core.parse import parse_workbook
    from engines.t2pbi.ir import SERIES

    workbook = parse_workbook(
        (Path(__file__).parent / "fixtures" / "shelves.twb").read_bytes()
    )
    sheet = workbook.worksheets[0]
    assert [b.field for b in sheet.placed(SERIES)] == ["Category"]
