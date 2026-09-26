"""What a filter actually does, and reporting only the work that is real.

Superstore raises 83 filter flags, every one of them `MANUAL` and every one
saying *"This worksheet filter is not carried over; recreate it"*. Counting what
those filters actually are:

    50  level-members, ui-enumeration="all"  - selects every member
    13  crossjoin                             - compound, across fields
    11  quantitative range                    - a real restriction
     7  categorical with a member list        - a real restriction
     1  categorical range covering the whole domain
     7  :Measure Names                        - no Power BI equivalent

**Around eighteen of the eighty-three restrict anything.** The other sixty-five
are filter-shelf entries with everything selected, and the report was telling a
consultant to go and recreate all of them.

That is a trust bug pointing the opposite way from the usual one. This product
is built to never claim more than it did; over-claiming the *work left to do* is
the same failure wearing different clothes, and it is more corrosive than it
looks. A person who checks the first six items, finds all six are nothing, stops
reading - and the twelve that genuinely change what the report shows are in the
part they stopped reading.

The cause was in the parser: only the filter's *field* was kept, and the
`<groupfilter>` children saying what it does were dropped. Nothing downstream
could tell "Category, all values" from "Category, two values" because by then
they were the same object.
"""

from __future__ import annotations

import pytest

from t2pbi.core.parse import parse_workbook
from t2pbi.ir import Severity

WORKBOOK = b"""<?xml version='1.0' encoding='utf-8' ?>
<workbook version='2021.4'>
  <datasources>
    <datasource name='Parameters' />
    <datasource name='federated.f' caption='Orders'>
      <connection class='sqlserver' />
      <column name='[Category]' datatype='string' role='dimension' />
      <column name='[Region]' datatype='string' role='dimension' />
      <column name='[Sales]' datatype='real' role='measure' />
      <column name='[Profit]' datatype='real' role='measure' />
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name='Sheet'>
      <table>
        <view>
          <rows>[federated.f].[sum:Sales:qk]</rows>
          <cols>[federated.f].[none:Category:nk]</cols>
          <filter class='categorical' column='[federated.f].[none:Category:nk]'>
            <groupfilter function='level-members' level='[none:Category:nk]' />
          </filter>
          <filter class='categorical' column='[federated.f].[none:Region:nk]'>
            <groupfilter function='union'>
              <groupfilter function='member' level='[none:Region:nk]' member='&quot;West&quot;' />
              <groupfilter function='member' level='[none:Region:nk]' member='&quot;East&quot;' />
            </groupfilter>
          </filter>
          <filter class='quantitative' column='[federated.f].[sum:Profit:qk]'>
            <min>0</min>
            <max>500</max>
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
def workbook():
    """Parsed *and* mapped.

    The filter flags are raised by the mapping stage, not the parser - parsing
    reads what the filter does, mapping decides what to say about it. A first
    version of this fixture only parsed, and every flag assertion failed
    against an empty list, which looked like the feature was missing.
    """
    from t2pbi.core.mapping.visual_map import map_visuals

    wb = parse_workbook(WORKBOOK)
    map_visuals(wb)
    return wb


def _filters(workbook):
    return {f.field: f for f in workbook.worksheets[0].filters}


# --- what the parser now keeps -------------------------------------------------------


def test_a_filter_that_selects_every_member_says_so(workbook):
    """`level-members` with no member list is Tableau's "all"."""
    assert _filters(workbook)["Category"].restricts is False


def test_a_filter_with_a_member_list_is_a_restriction(workbook):
    assert _filters(workbook)["Region"].restricts is True


def test_the_members_are_kept_so_the_filter_can_be_rebuilt(workbook):
    """Keeping only the field is what made every filter look alike. The values
    are the filter; without them there is nothing to carry across."""
    assert _filters(workbook)["Region"].members == ("East", "West")


def test_a_range_filter_keeps_its_bounds(workbook):
    profit = _filters(workbook)["Profit"]
    assert profit.restricts is True
    assert (profit.minimum, profit.maximum) == ("0", "500")


def test_a_filter_that_restricts_nothing_keeps_no_members(workbook):
    assert _filters(workbook)["Category"].members == ()


# --- what the report now says --------------------------------------------------------


def test_a_filter_that_restricts_nothing_is_not_reported_as_manual_work(workbook):
    """The trust bug. Sixty-five of Superstore's eighty-three said "recreate
    this" about a filter with everything selected."""
    flags = [f for f in workbook.flags if f.item.endswith("Category")]
    assert flags, "the filter is still reported - it is not silently dropped"
    assert all(f.severity is not Severity.MANUAL for f in flags), [
        f.reason for f in flags
    ]


def test_it_is_still_reported_because_nothing_is_ever_silently_dropped(workbook):
    """Not manual work is not the same as not worth mentioning. The filter
    shelf entry existed and the converted report does not have it."""
    reasons = " ".join(f.reason for f in workbook.flags if f.item.endswith("Category"))
    assert "every value" in reasons or "all values" in reasons


def test_a_restriction_that_is_not_converted_is_still_manual_work(workbook):
    """The ones that matter must keep their weight, which is the whole point of
    quietening the sixty-five.

    `Region` used to be here too. It is now carried into the report as a real
    Power BI filter (`test_filter_conversion.py`), so calling it manual work
    would be the same over-claim in a new place - this time about a filter that
    is already in the file. The range on `Profit` is over an aggregate with no
    measure behind it and is still a rebuild.
    """
    flags = [f for f in workbook.flags if f.item.endswith("Profit")]
    assert flags
    assert any(f.severity is Severity.MANUAL for f in flags)


def test_the_restricting_flag_names_the_values_so_it_can_be_rebuilt(workbook):
    """"Recreate this filter" without the values is a puzzle, not an
    instruction: the consultant has to open Tableau to find out what it was."""
    reason = next(f.reason for f in workbook.flags if f.item.endswith("Region"))
    assert "West" in reason and "East" in reason


def test_the_range_flag_names_its_bounds(workbook):
    reason = next(f.reason for f in workbook.flags if f.item.endswith("Profit"))
    assert "0" in reason and "500" in reason


# --- the real workbook ----------------------------------------------------------------


def test_superstore_stops_over_reporting_filter_work():
    """The measurement that started this, if the workbook is present.

    Not a fixed number - the point is that the manual count is far below the
    total, because most of Superstore's filters select everything.
    """
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "testing_content" / "Superstore.twb"
    if not real.is_file():
        pytest.skip("Superstore.twb is not in this checkout")

    from t2pbi.core.mapping.visual_map import map_visuals

    wb = parse_workbook(real.read_bytes())
    map_visuals(wb)
    filter_flags = [f for f in wb.flags if "filter" in f.reason.lower()]
    manual = [f for f in filter_flags if f.severity is Severity.MANUAL]
    assert filter_flags, "filters are still reported"
    assert len(manual) < len(filter_flags) / 2, (
        f"{len(manual)} of {len(filter_flags)} filters still reported as manual "
        "work; most of this workbook's filters select every value"
    )


def test_a_member_that_is_a_shelf_reference_is_shown_as_the_field_it_names():
    """A `:Measure Names` filter's members are references, not values.

    Tableau writes them as `[federated.0a01cod...].[min:Base (Variable):qk]`.
    Printing that under "this filter keeps only ..." shows a consultant machine
    text where they expect a value they recognise - which is worse than showing
    nothing, because it looks like data and is not.

    Found by breaking the decoding and watching no test fail: the fixture above
    uses plain values, so nothing covered the shape the real workbook has.
    """
    from t2pbi.core.mapping.visual_map import map_visuals

    xml = WORKBOOK.replace(
        b"""<groupfilter function='member' level='[none:Region:nk]' member='&quot;West&quot;' />""",
        b"""<groupfilter function='member' level='[none:Region:nk]' member='&quot;[federated.f].[min:Base (Variable):qk]&quot;' />""",
    )
    wb = parse_workbook(xml)
    map_visuals(wb)

    members = {f.field: f for f in wb.worksheets[0].filters}["Region"].members
    assert "Base (Variable)" in members
    assert not any(m.startswith("[federated") for m in members), members
