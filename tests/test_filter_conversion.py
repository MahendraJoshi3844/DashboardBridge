"""Carrying a Tableau filter across, instead of only describing it.

`test_filter_restriction.py` stopped the report over-claiming the work left:
of Superstore's 83 filters, ~18 restrict anything and the rest are filter shelf
entries with every value selected. This file is the next step - converting the
ones that can be converted, and saying so.

Two things are being tested, and the first one matters more than the second.

**Reading `except` correctly.** Tableau writes "everything but these" as a
`<groupfilter function="except">` wrapping a `level-members` (the universe) and
the members to remove. The parser only looked for `member` descendants, so
Superstore's one `except` filter - *all cities except null* - was read as *keeps
only null*, and the migration report said so. That is not a missing feature; it
is the report stating the opposite of the truth about the user's data, which is
the worst failure this product has. It was found while measuring what could be
emitted, one step before it would have been emitted that way too.

**Emitting `filterConfig`.** The format is not guessed. It comes from Desktop's
own `FilterConfigurationSerializer` and `SemanticQuerySerializer` in
`desktop.min.js`: a filter is `{name, field, type, filter}`, the inner `filter`
is `{Version: 2, From: [...], Where: [...]}`, `In` serialises as
`{In: {Expressions, Values}}`, `Not` as `{Not: {Expression}}`, a column as
`{Column: {Expression: {SourceRef: {...}}, Property}}`, and a literal as
`{Literal: {Value}}` with text encoded `'like this'` and null as `null`. See
`test_pbir_schema_versions.py` for how those numbers are read out of the bundle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engines.t2pbi.core.mapping.visual_map import map_visuals
from engines.t2pbi.core.parse import parse_workbook
from engines.t2pbi.ir import Severity

ROOT = Path(__file__).resolve().parents[1]

WORKBOOK = b"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='2021.4'>
  <datasources>
    <datasource name='Parameters' />
    <datasource name='federated.f' caption='Orders'>
      <connection class='sqlserver' />
      <column name='[City]' datatype='string' role='dimension' />
      <column name='[Region]' datatype='string' role='dimension' />
      <column name='[Order Date]' datatype='datetime' role='dimension' />
      <column name='[Sales]' datatype='real' role='measure' />
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Sheet'>
      <table>
        <view>
          <rows>[federated.f].[sum:Sales:qk]</rows>
          <cols>[federated.f].[none:Region:nk]</cols>
          <filter class='categorical' column='[federated.f].[none:Region:nk]'>
            <groupfilter function='union'>
              <groupfilter function='member' level='[none:Region:nk]' member='&quot;West&quot;' />
              <groupfilter function='member' level='[none:Region:nk]' member='&quot;East&quot;' />
            </groupfilter>
          </filter>
          <filter class='categorical' column='[federated.f].[none:City:nk]'>
            <groupfilter function='except'>
              <groupfilter function='level-members' level='[none:City:nk]' />
              <groupfilter function='member' level='[none:City:nk]' member='%null%' />
            </groupfilter>
          </filter>
          <filter class='categorical' column='[federated.f].[none:Order Date:nk]'>
            <groupfilter function='union'>
              <groupfilter function='member' level='[none:Order Date:nk]' member='#2016-01-01#' />
            </groupfilter>
          </filter>
        </view>
        <panes><pane><mark class='Bar' /></pane></panes>
      </table>
    </worksheet>
  </worksheets>
  <dashboards />
</workbook>
"""


@pytest.fixture(scope="module")
def mapped():
    wb = parse_workbook(WORKBOOK)
    visuals = map_visuals(wb)
    return wb, visuals


def _filters(wb):
    return {f.field: f for f in wb.worksheets[0].filters}


def _flags_for(wb, field):
    return [f for f in wb.flags if f.item.endswith(f": {field}")]


# --- reading `except` ------------------------------------------------------------------


def test_except_is_read_as_exclusion_not_selection(mapped):
    """The bug this file was written for.

    `except(level-members, member %null%)` is *every city but the blanks*. Read
    as a member list it becomes *only the blanks* - the opposite - and the
    report printed that opposite to the user.
    """
    wb, _ = mapped
    city = _filters(wb)["City"]
    assert city.restricts is True
    assert city.excludes is True
    assert city.members == ("%null%",)


def test_a_plain_member_list_is_still_a_selection(mapped):
    wb, _ = mapped
    region = _filters(wb)["Region"]
    assert region.excludes is False
    assert region.members == ("East", "West")


def test_the_except_flag_says_except(mapped):
    """"Keeps only: (blank)" and "keeps everything except (blank)" describe
    different data. The sentence has to carry the direction."""
    wb, _ = mapped
    reason = _flags_for(wb, "City")[0].reason
    assert "except" in reason.lower()
    assert "keeps only" not in reason.lower()


def test_the_null_member_is_shown_as_blank_not_as_tableaus_sentinel(mapped):
    """`%null%` is Tableau's internal marker. A consultant reading the report
    should see the word Power BI uses, not the source tool's encoding."""
    wb, _ = mapped
    reason = _flags_for(wb, "City")[0].reason
    assert "%null%" not in reason
    assert "blank" in reason.lower()


# --- what gets converted ---------------------------------------------------------------


def test_a_string_member_filter_is_carried_across(mapped):
    _, visuals = mapped
    carried = {f.field.column for f in visuals[0].filters}
    assert "Region" in carried


def test_a_converted_filter_is_no_longer_reported_as_manual_work(mapped):
    """The trust contract in the other direction. Telling someone to rebuild a
    filter that is already in the file wastes exactly as much of their time as
    not telling them about one that is missing."""
    wb, _ = mapped
    flags = _flags_for(wb, "Region")
    assert flags
    assert all(f.severity is not Severity.MANUAL for f in flags), [
        f.reason for f in flags
    ]
    assert "carried" in " ".join(f.reason for f in flags).lower()


def test_a_date_member_filter_is_not_converted(mapped):
    """Tableau writes a date member as `#2016-01-01#`; Power BI wants
    `datetime'2016-01-01T00:00:00'`. Whether that is a date or a datetime, and
    in whose timezone, is not stated in the workbook - so it is a guess, and
    guesses are the one thing this converter does not emit."""
    _, visuals = mapped
    assert "Order Date" not in {f.field.column for f in visuals[0].filters}


def test_an_unconverted_restriction_is_still_manual_work(mapped):
    wb, _ = mapped
    flags = _flags_for(wb, "Order Date")
    assert flags
    assert any(f.severity is Severity.MANUAL for f in flags)


# --- the file Power BI reads -----------------------------------------------------------


def _page_json(tmp_path, visuals):
    from engines.t2pbi.core.emit.pbir import write_report_definition

    write_report_definition(visuals, tmp_path, emit_filters=True)
    pages = sorted((tmp_path / "definition" / "pages").glob("*/page.json"))
    return [json.loads(p.read_text(encoding="utf-8")) for p in pages]


def test_the_page_carries_a_filter_config(mapped, tmp_path):
    _, visuals = mapped
    page = _page_json(tmp_path, visuals)[0]
    names = {
        f["field"]["Column"]["Property"] for f in page["filterConfig"]["filters"]
    }
    assert names == {"Region", "City"}


def test_a_selection_serialises_as_In_over_encoded_literals(mapped, tmp_path):
    """Desktop's `visitIn` writes `{In: {Expressions, Values}}` and its literal
    decoder reads text as `'quoted'`, so that is what is written here."""
    _, visuals = mapped
    page = _page_json(tmp_path, visuals)[0]
    region = next(
        f
        for f in page["filterConfig"]["filters"]
        if f["field"]["Column"]["Property"] == "Region"
    )
    assert region["type"] == "Categorical"
    assert region["filter"]["Version"] == 2
    assert region["filter"]["From"] == [
        {"Name": "o", "Entity": "Orders", "Type": 0}
    ]
    condition = region["filter"]["Where"][0]["Condition"]
    assert condition["In"]["Expressions"] == [
        {
            "Column": {
                "Expression": {"SourceRef": {"Source": "o"}},
                "Property": "Region",
            }
        }
    ]
    assert condition["In"]["Values"] == [
        [{"Literal": {"Value": "'East'"}}],
        [{"Literal": {"Value": "'West'"}}],
    ]


def test_an_exclusion_serialises_as_Not_around_In(mapped, tmp_path):
    """`visitNot` is `{Not: {Expression}}`, and Desktop's literal decoder reads
    the bare word `null` as null - which is what `%null%` means."""
    _, visuals = mapped
    page = _page_json(tmp_path, visuals)[0]
    city = next(
        f
        for f in page["filterConfig"]["filters"]
        if f["field"]["Column"]["Property"] == "City"
    )
    inner = city["filter"]["Where"][0]["Condition"]["Not"]["Expression"]
    assert inner["In"]["Values"] == [[{"Literal": {"Value": "null"}}]]


def test_the_field_is_standalone_and_the_condition_is_aliased(mapped, tmp_path):
    """Two different serialisations of the same column, and they are not
    interchangeable: `serializeExpr` is standalone and names the entity, while
    the `Where` clause goes through `serializeQueryFilters` with standalone
    false and names the `From` alias. Writing an alias in `field` or an entity
    in `Where` is a file Desktop cannot resolve."""
    _, visuals = mapped
    page = _page_json(tmp_path, visuals)[0]
    filt = page["filterConfig"]["filters"][0]
    assert filt["field"]["Column"]["Expression"] == {"SourceRef": {"Entity": "Orders"}}
    where = json.dumps(filt["filter"]["Where"])
    assert '"Entity"' not in where


def test_a_page_with_nothing_to_convert_has_no_filter_config(tmp_path):
    """An empty `filterConfig` is not the same as no filters, and Desktop's own
    serializer returns undefined rather than writing an empty object.

    The first version of this test kept the convertible filters in the fixture,
    so the page always had a `filterConfig` and the assertion could not fail.
    Found by making `filter_config` return `{"filters": []}` and watching
    nothing go red.
    """
    xml = WORKBOOK
    for keep in (b"none:Region:nk", b"none:City:nk"):
        xml = xml.replace(keep, b"none:Order Date:nk")
    wb = parse_workbook(xml)
    visuals = map_visuals(wb)
    assert visuals[0].filters == [], "fixture no longer has nothing to convert"
    page = _page_json(tmp_path, visuals)[0]
    assert "filterConfig" not in page


def test_filter_names_are_deterministic(mapped, tmp_path):
    """Same input, identical output - including the generated filter ids, which
    Desktop makes up at random when it writes one itself."""
    _, visuals = mapped
    first = _page_json(tmp_path / "a", visuals)[0]
    second = _page_json(tmp_path / "b", visuals)[0]
    assert first == second
    names = [f["name"] for f in first["filterConfig"]["filters"]]
    assert len(set(names)) == len(names)


def test_the_filter_names_the_column_as_the_model_writes_it(tmp_path):
    """A shelf may name a field by its internal name while TMDL writes the
    caption, and only the emitting stage knows which is in the file.

    This is the whole reason `_bind_to_emitted` exists for field wells, and the
    first version of this feature bypassed it entirely: `_bind_to_emitted`
    rebuilds each `PBIVisual`, so the filters were rebuilt away and no page had
    a `filterConfig` at all. That seam is what this exercises.
    """
    from engines.t2pbi.core.emit.pbip import _bind_to_emitted

    xml = WORKBOOK.replace(
        b"<column name='[Region]' datatype='string' role='dimension' />",
        b"<column name='[Region]' caption='Sales Region' datatype='string' "
        b"role='dimension' />",
    )
    wb = parse_workbook(xml)
    bound = _bind_to_emitted(wb, map_visuals(wb))
    page = _page_json(tmp_path, bound)[0]

    properties = {
        f["field"]["Column"]["Property"] for f in page["filterConfig"]["filters"]
    }
    assert "Sales Region" in properties
    assert "Region" not in properties


def test_filters_are_not_written_unless_they_are_asked_for(mapped, tmp_path):
    """The default is off, and the reason is evidence rather than code.

    Every part of the `filterConfig` shape is read out of Desktop's own
    serializer and tested - and no Desktop has yet opened a project containing
    one. The first that tried failed to render. Writing it by default would be
    the guess this converter refuses everywhere else, so the filter is reported
    as manual work with its values named until a Desktop says otherwise.
    """
    from engines.t2pbi.core.emit.pbir import write_report_definition

    _, visuals = mapped
    assert visuals[0].filters, "the fixture still has something to write"
    write_report_definition(visuals, tmp_path)
    for path in (tmp_path / "definition" / "pages").glob("*/page.json"):
        assert "filterConfig" not in json.loads(path.read_text("utf-8"))


def test_a_page_is_declared_at_the_version_whose_shape_it_is_written_in(
    mapped, tmp_path
):
    """`1.0.0`, and the reasoning that moved it to `1.4.0` was backwards.

    Desktop picks its *upgrader* chain from the declared version: a page that
    says 1.0.0 is normalised forward, and one that says 1.4.0 is taken at its
    word as already being that shape. This emitter writes the 1.0.0 shape, so
    claiming 1.4.0 skipped the code that would have made the claim true - and
    Desktop stopped rendering the report.
    """
    _, visuals = mapped
    for page in _page_json(tmp_path, visuals):
        assert "/page/1.0.0/schema.json" in page["$schema"]


# --- the real workbook ------------------------------------------------------------------


def test_superstore_never_filters_a_column_that_is_not_in_the_model():
    """The failure mode that costs a Desktop round trip.

    A `filterConfig` naming a column the semantic model does not have is not a
    degraded report - it is a report that will not resolve. Every emitted filter
    must point at a table and column the emitter also wrote.
    """
    real = ROOT / "testing_content" / "Superstore.twb"
    if not real.is_file():
        pytest.skip("Superstore.twb is not in this checkout")

    wb = parse_workbook(real.read_bytes())
    visuals = map_visuals(wb)
    known = {
        (table.name, column.name)
        for table in wb.all_tables()
        for column in table.columns
    }
    unknown = [
        (f.field.table, f.field.column)
        for visual in visuals
        for f in visual.filters
        if (f.field.table, f.field.column) not in known
    ]
    assert unknown == [], unknown


def test_superstore_reads_its_one_exclusion_filter_the_right_way_round():
    """The bug in the real file it was found in: Product Detail Sheet filters
    City to everything except the blanks."""
    real = ROOT / "testing_content" / "Superstore.twb"
    if not real.is_file():
        pytest.skip("Superstore.twb is not in this checkout")

    wb = parse_workbook(real.read_bytes())
    excluding = [
        (ws.name, f.field, f.members)
        for ws in wb.worksheets
        for f in ws.filters
        if f.excludes
    ]
    assert ("Product Detail Sheet", "City", ("%null%",)) in excluding
