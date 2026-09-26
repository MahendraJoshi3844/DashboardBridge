"""A workbook whose tables reuse each other's field names, end to end.

`tests/fixtures/clashes.twb`. The other scoping tests
(`test_dependency_graph.py`) build the IR by hand, which is fast and precise but
skips the parser, the grain fixpoint's real inputs, and the emitter. This runs
the whole pipeline over a real `.twb`, because the defect these guard against
was only visible once all three agreed on what a name meant.

Superstore, the only realistic fixture until now, has no cross-table clash: every
reference in it resolves the same way whether or not the resolver knows which
table asked. It could never have caught any of this.

Each assertion below fails on the pre-`P3.2` engine - verified by reverting each
of the three fixes in turn.
"""

from __future__ import annotations

import pytest

from t2pbi.pipeline import run


@pytest.fixture
def converted(clashing_twb_path, tmp_path):
    return run(clashing_twb_path, tmp_path / "out", "Clashes").workbook


def _dax(wb) -> dict[str, str | None]:
    return {
        f"{table.name}.{col.display_name}": col.dax
        for table in wb.all_tables()
        for col in table.columns
        if col.is_calculated
    }


def _reasons(wb) -> dict[str, str]:
    return {flag.item: flag.reason for flag in wb.flags}


def test_the_three_tables_keep_their_clashing_names(converted):
    """The clash has to survive parsing, or the fixture proves nothing."""
    assert [table.name for table in converted.all_tables()] == [
        "Orders",
        "Targets",
        "Returns",
    ]
    named_sales = {
        table.name
        for table in converted.all_tables()
        for col in table.columns
        if col.display_name == "Sales"
    }
    assert named_sales == {"Orders", "Targets"}


def test_a_formula_reads_its_own_table_not_a_measure_of_the_same_name(converted):
    """`Targets` holds a measure called `Sales`; `Orders` holds a column.

    Resolving to the measure would emit DAX that quietly reads a different
    table's number - the kind of wrong answer that looks entirely plausible in
    a report.
    """
    assert (
        _dax(converted)["Orders.Profit Ratio"]
        == "SUM('Orders'[Profit]) / SUM('Orders'[Sales])"
    )


def test_a_refused_calc_elsewhere_does_not_refuse_a_column_of_the_same_name(converted):
    """`Returns.Quantity` is refused; `Orders.Quantity` is a physical column.

    This is the case the old propagation got wrong: it asked whether
    `[Quantity]` appeared in the emitted DAX, and found it inside
    `'Orders'[Quantity]`.
    """
    dax = _dax(converted)
    assert dax["Returns.Quantity"] is None, "a table calculation is still refused"
    assert (
        dax["Orders.Units per Order"]
        == "SUM('Orders'[Quantity]) / DISTINCTCOUNT('Orders'[Order ID])"
    )


def test_a_local_measure_of_a_clashing_name_still_resolves_to_itself(converted):
    """Inside `Targets`, `[Sales]` really is Targets' own calculation.

    Preferring the local table must not go so far that a table stops seeing its
    own measures.
    """
    assert _dax(converted)["Targets.Attainment"] == "[Sales] / SUM('Targets'[Quota])"


def test_a_calc_that_truly_depends_on_a_refused_one_is_still_refused(converted):
    """Precision has to cut both ways, or the fix is a different wrong answer."""
    assert _dax(converted)["Returns.Return Rate"] is None
    assert "Quantity" in _reasons(converted)["Returns.Return Rate"]


def test_the_refusal_names_the_construct_rather_than_the_clash(converted):
    """`Returns.Quantity` is refused for what it is, not for its name."""
    assert "RUNNING_" in _reasons(converted)["Returns.Quantity"]


def test_a_translation_that_fired_two_rules_cites_both(converted):
    units = next(
        col
        for table in converted.all_tables()
        for col in table.columns
        if col.display_name == "Units per Order"
    )
    assert units.dax_rule_ids == [
        "TABLEAU_COUNTD_TO_PBI_DISTINCTCOUNT",
        "TABLEAU_SUM_TO_PBI_SUM",
    ]


def test_every_measure_the_dax_references_is_defined_by_the_model(converted):
    """No emitted expression may name a measure the model does not carry.

    A dangling reference fails only when someone opens the file, which is the
    surprise this product exists to prevent - and a workbook full of name
    clashes is where a resolver is most likely to produce one.
    """
    import re

    measure_ref = re.compile(r"(?<!')\[([^\[\]]+)\]")
    defined = {
        col.display_name
        for table in converted.all_tables()
        for col in table.columns
        if col.is_aggregate
    } | {f"{param.display_name} Value" for param in converted.parameters}

    for table in converted.all_tables():
        for col in table.columns:
            if not col.dax:
                continue
            for name in measure_ref.findall(col.dax):
                assert name in defined, (
                    f"{table.name}.{col.display_name} references [{name}], "
                    "which the model never defines"
                )


def test_converting_it_twice_produces_the_same_answer(clashing_twb_path, tmp_path):
    """Determinism, on the workbook most able to break it.

    Resolution here depends on which table is asking, so a resolver that leaned
    on dict ordering anywhere would show it on this file first.
    """
    first = run(clashing_twb_path, tmp_path / "a", "Clashes").workbook
    second = run(clashing_twb_path, tmp_path / "b", "Clashes").workbook

    assert _dax(first) == _dax(second)
    assert [(f.item, f.reason) for f in first.flags] == [
        (f.item, f.reason) for f in second.flags
    ]
