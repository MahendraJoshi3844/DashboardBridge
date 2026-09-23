from dataclasses import replace

from engines.t2pbi.core.mapping import map_visuals
from engines.t2pbi.core.parse import parse_workbook


def test_maps_worksheet_to_powerbi_visual(sample_twb_bytes):
    wb = parse_workbook(sample_twb_bytes)
    visuals = map_visuals(wb)
    assert len(visuals) == 1
    v = visuals[0]
    assert v.name == "Sales by Date"
    assert v.visual_type == "clusteredBarChart"  # bar -> clusteredBarChart
    # cols -> category (Order Date), rows -> values (Sales)
    assert [f.column for f in v.category] == ["Order Date"]
    assert [f.column for f in v.values] == ["Sales"]
    # fields resolve to the real table, not a guess
    assert v.values[0].table == wb.all_tables()[0].name


def test_unresolved_field_is_flagged(sample_twb_bytes):
    wb = parse_workbook(sample_twb_bytes)
    # Inject a worksheet referencing an unknown field.
    from engines.t2pbi.ir import VALUE, VisualBinding, Worksheet

    unknown = VisualBinding(raw="[DoesNotExist]", field="DoesNotExist")
    wb.worksheets.append(
        Worksheet(name="Bogus", visual_type="bar", bindings=[replace(unknown, role=VALUE)])
    )
    map_visuals(wb)
    assert any("DoesNotExist" in f.item for f in wb.flags)
