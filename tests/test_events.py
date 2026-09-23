"""The event spine: a recorded, ordered account of what the conversion did.

The UI binds to a Timeline rather than to progress percentages, so live streaming
and replay are the same renderer at different clock positions. That only holds if
the recording is complete, ordered, and serializable.
"""

import json

from engines.t2pbi.events import NULL_SINK, ConversionEvent, EventSink, Timeline


def test_sink_numbers_events_in_emission_order():
    sink = EventSink()
    sink.emit("Parse", "table", "Orders", "crossed")
    sink.emit("Parse", "table", "People", "crossed")
    assert [e.seq for e in sink.timeline().events] == [0, 1]
    assert [e.name for e in sink.timeline().events] == ["Orders", "People"]


def test_events_record_when_they_happened():
    sink = EventSink()
    sink.emit("Parse", "table", "Orders", "crossed")
    event = sink.timeline().events[0]
    assert event.elapsed_ms >= 0


def test_timeline_partitions_crossed_from_held():
    sink = EventSink()
    sink.emit("Translate", "calc", "Profit Ratio", "crossed", detail="measure")
    sink.emit("Translate", "calc", "Sales Forecast", "held", detail="no aggregation")
    timeline = sink.timeline()
    assert [e.name for e in timeline.crossed()] == ["Profit Ratio"]
    assert [e.name for e in timeline.held()] == ["Sales Forecast"]


def test_timeline_serializes_to_json_for_the_ui_bridge():
    sink = EventSink()
    sink.emit("Map", "visual", "Sales by Date", "crossed", detail="clusteredBarChart")
    payload = json.dumps(sink.timeline().to_dict())
    assert "Sales by Date" in payload
    assert json.loads(payload)["events"][0]["outcome"] == "crossed"


def test_timeline_reports_the_real_elapsed_duration():
    sink = EventSink()
    sink.emit("Parse", "table", "Orders", "crossed")
    assert sink.timeline().duration_ms >= 0


def test_null_sink_records_nothing_and_accepts_everything():
    NULL_SINK.emit("Parse", "table", "Orders", "crossed")
    assert NULL_SINK.timeline().events == []


def test_event_rejects_an_unknown_outcome():
    """crossed/held drives which side of the seam an item lands on."""
    try:
        ConversionEvent(
            seq=0, elapsed_ms=0, stage="Parse", kind="table",
            name="Orders", outcome="maybe",
        )
    except ValueError:
        return
    raise AssertionError("an unknown outcome should not be constructible")


def test_timeline_round_trips_through_its_dict_form():
    sink = EventSink()
    sink.emit("Translate", "calc", "Profit Ratio", "crossed", detail="measure")
    restored = Timeline.from_dict(sink.timeline().to_dict())
    assert restored.events == sink.timeline().events
    assert restored.duration_ms == sink.timeline().duration_ms


def test_event_can_carry_the_source_and_its_translation():
    """The drill-down shows Tableau formula against emitted DAX, so the
    recording has to carry both - a second round-trip per item would make the
    proof panel feel laggy in a demo."""
    sink = EventSink()
    sink.emit(
        "Translate", "calc", "Profit Ratio", "crossed", detail="measure",
        source="SUM([Profit])/SUM([Sales])",
        result="SUM('Orders'[Profit])/SUM('Orders'[Sales])",
    )
    event = sink.timeline().events[0]
    assert event.source == "SUM([Profit])/SUM([Sales])"
    assert event.result.startswith("SUM('Orders'")


def test_held_event_carries_its_source_but_no_translation():
    sink = EventSink()
    sink.emit(
        "Translate", "calc", "Forecast", "held",
        detail="no aggregation stated", source="[Sales]*(1+[Rate])",
    )
    event = sink.timeline().events[0]
    assert event.source == "[Sales]*(1+[Rate])"
    assert event.result == ""
