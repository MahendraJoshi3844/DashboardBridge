"""A visual with nothing on it is not written (`P3` acceptance).

Found by bisecting a project Power BI Desktop refused to render. The report
opened with its visuals removed and crashed with them present, which narrowed
the fault to `visual.json`; five of Superstore's twenty-one visuals were being
written with `"queryState": {}` - a visual container claiming a visual exists,
with no field on it at all.

Whether an empty container is what crashes Desktop is not settled here, and this
change does not depend on it. Writing one is wrong on its own terms:

* It is a claim. `visual.json` on disk says a chart was produced. Nothing was
  produced - every field that would have gone on it failed to map, and each of
  those failures is already a `MANUAL` flag telling the user to place the field
  by hand.
* The flag beside it said so out loud. "Visual generated as 'clusteredBarChart'
  - verify layout in Power BI Desktop" is not true of a container with no
  fields, and it is exactly the kind of statement this product exists not to
  make. It now says what actually happened.

A `scatterChart` is the same problem wearing different clothes. Its wells come
from `_DEFAULT_WELLS`, which fills `Category` and `Y` - so a scatter is written
with no `X` at all. A scatter plot without an X axis is not a scatter plot, and
guessing which measure belongs on X is precisely the guess this converter
refuses to make elsewhere.

The page is kept in both cases. The worksheet existed, the page records that it
existed, and an empty page next to a flag that says why is a smaller loss than a
page that is not there.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from t2pbi import pipeline

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    out = tmp_path_factory.mktemp("pbip")
    result = pipeline.run(FIXTURES / "unbindable.twb", out)
    project = Path(result.pbip_path)
    root = project.parent if project.is_file() else project
    return next(root.glob("*.Report/definition")), result


def _visuals(definition: Path) -> list[dict]:
    return [
        json.loads(p.read_text("utf-8"))
        for p in sorted(definition.glob("pages/*/visuals/*/visual.json"))
    ]


# --- what is not written ----------------------------------------------------------


def test_no_visual_is_written_with_an_empty_query_state(converted):
    """The defect. A container with no fields is a claim that a chart exists."""
    definition, _ = converted
    empty = [
        v["name"]
        for v in _visuals(definition)
        if not v["visual"].get("query", {}).get("queryState")
    ]
    assert empty == [], f"{len(empty)} visuals were written with nothing on them"


def test_no_scatter_is_written_without_an_x_axis(converted):
    """`_DEFAULT_WELLS` fills Category and Y, so a scatter never gets an X.

    Choosing which measure goes on X is a guess, and the converter does not
    guess - so it does not write the visual either.
    """
    definition, _ = converted
    for visual in _visuals(definition):
        if visual["visual"]["visualType"] == "scatterChart":
            wells = set(visual["visual"]["query"]["queryState"])
            assert "X" in wells, f"scatter {visual['name']} has wells {sorted(wells)}"


# --- what is still written --------------------------------------------------------


def test_a_worksheet_whose_fields_mapped_still_becomes_a_visual(converted):
    """A limit that costs the product its working output is not a fix."""
    definition, _ = converted
    visuals = _visuals(definition)
    assert visuals, "no visuals at all were written"
    for visual in visuals:
        assert visual["visual"]["query"]["queryState"]


def test_the_page_is_kept_even_when_its_visual_is_not(converted):
    """The worksheet existed. The page records that, and the flag says why it
    is empty - which is a smaller loss than a page that is simply absent."""
    definition, _ = converted
    pages = list((definition / "pages").glob("*/page.json"))
    visuals = _visuals(definition)
    assert len(pages) >= len(visuals)


# --- what is claimed --------------------------------------------------------------


def test_nothing_claims_a_visual_was_generated_when_none_was(converted):
    """The flag beside an empty visual said "Visual generated as ...".

    That is the statement this product exists not to make. Every "generated as"
    flag must now correspond to a visual that is actually on disk.
    """
    definition, result = converted
    written = {
        p.parent.parent.parent.name: True
        for p in definition.glob("pages/*/visuals/*/visual.json")
    }
    claimed = [
        flag.item
        for flag in result.workbook.flags
        if "Visual generated as" in flag.reason
    ]
    pages = {
        json.loads(p.read_text("utf-8"))["displayName"]: p.parent.name
        for p in definition.glob("pages/*/page.json")
    }
    for item in claimed:
        page_id = pages.get(item)
        assert page_id in written, (
            f"a flag says a visual was generated for {item!r}, and none was written"
        )


def test_a_worksheet_with_no_bindable_field_says_so(converted):
    """Absent is not the same as silently absent.

    If no visual was written for a worksheet, some flag has to name that
    worksheet - otherwise the page is empty and the report explains nothing.
    """
    definition, result = converted
    pages = {
        json.loads(p.read_text("utf-8"))["displayName"]: p.parent.name
        for p in definition.glob("pages/*/page.json")
    }
    written = {p.parent.parent.parent.name for p in definition.glob("pages/*/visuals/*/visual.json")}
    named = {flag.item.split(":")[0].strip() for flag in result.workbook.flags}
    for worksheet, page_id in pages.items():
        if page_id not in written:
            assert worksheet in named, f"{worksheet} has no visual and no flag"


def test_a_worksheet_that_produced_no_visual_counts_as_needing_a_person(converted):
    """Severity, not just wording.

    `MANUAL` is what puts an item in the "needs a person" count; `INFO` is a
    note beside work that was done. A worksheet whose visual was not written is
    work somebody still has to do, so reporting it as INFO would leave it out
    of the number the user plans around - the same under-reporting as claiming
    the visual existed, arrived at by a different route.
    """
    from t2pbi.ir import Severity

    definition, result = converted
    written = {
        p.parent.parent.parent.name
        for p in definition.glob("pages/*/visuals/*/visual.json")
    }
    pages = {
        json.loads(p.read_text("utf-8"))["displayName"]: p.parent.name
        for p in definition.glob("pages/*/page.json")
    }
    unwritten = {name for name, page in pages.items() if page not in written}
    assert unwritten, "the fixture no longer exercises an unwritten visual"

    by_item = {
        flag.item: flag
        for flag in result.workbook.flags
        if flag.stage == "visual_map" and flag.item in unwritten
    }
    for name in unwritten:
        assert name in by_item, f"{name} has no visual_map flag"
        assert by_item[name].severity is Severity.MANUAL, (
            f"{name} produced no visual but is reported as "
            f"{by_item[name].severity}"
        )
