"""Conversion in dependency order (`P3.2`).

06-conversion-engine.md, "Orchestrator": build a dependency graph, classify
grain to a fixpoint, convert in dependency order, then propagate refusals.

The fixpoint existed. The graph did not, and its absence showed up as two false
refusals with the same root cause: a field reference was resolved by bare name
across the whole workbook, ignoring which table the calculation lives in.

Neither produced wrong DAX - the engine refuses rather than guesses, which is
the right bias - but both reported a calculation that converts perfectly as one
a person has to rebuild. Coverage lost for no reason is not a safe failure; it
is the product understating itself, in a document a client reads.
"""

from __future__ import annotations

from t2pbi.ir import Column, DataSource, Table, Workbook
from t2pbi.pipeline import _translate_calculations


def _workbook(*tables: Table) -> Workbook:
    return Workbook(
        datasources=[DataSource(name="ds", connection="none", tables=list(tables))]
    )


def _calc(name: str, formula: str) -> Column:
    return Column(name=name, datatype="real", role="measure", formula=formula)


def _column(name: str) -> Column:
    return Column(name=name, datatype="real", role="measure")


def _daxes(wb: Workbook) -> dict[str, str | None]:
    return {
        f"{table.name}.{col.display_name}": col.dax
        for table in wb.all_tables()
        for col in table.columns
        if col.is_calculated
    }


def test_a_calc_is_not_refused_because_another_table_names_a_calc_after_its_column():
    """The false refusal, in full.

    `Orders.Profit Ratio` reads `Orders`'s own `Sales` column. `Targets` happens
    to contain a *calculation* also called `Sales`, which is refused. Deciding
    "B depends on A" by asking whether `[A]` appears in B's emitted DAX makes
    `'Orders'[Sales]` look like a reference to that calculation, and drags a
    working translation down with it.
    """
    wb = _workbook(
        Table(
            name="Orders",
            columns=[
                _column("Profit"),
                _column("Sales"),
                _calc("Profit Ratio", "sum([Profit])/sum([Sales])"),
            ],
        ),
        Table(
            name="Targets",
            columns=[_column("Quota"), _calc("Sales", "RANK(SUM([Quota]))")],
        ),
    )
    _translate_calculations(wb)

    dax = _daxes(wb)
    assert dax["Targets.Sales"] is None, "a table calculation is still refused"
    assert dax["Orders.Profit Ratio"] == (
        "SUM('Orders'[Profit])/SUM('Orders'[Sales])"
    ), "a calculation reading its own table's column was refused for a name clash"


def test_a_calc_that_really_depends_on_a_refused_one_is_still_refused():
    """The propagation itself must survive being made precise."""
    wb = _workbook(
        Table(
            name="Orders",
            columns=[
                _column("Sales"),
                _calc("Ranked", "RANK(SUM([Sales]))"),
                _calc("Doubled", "[Ranked] * 2"),
            ],
        )
    )
    _translate_calculations(wb)

    dax = _daxes(wb)
    assert dax["Orders.Ranked"] is None
    assert dax["Orders.Doubled"] is None
    reasons = {flag.item: flag.reason for flag in wb.flags}
    assert "Ranked" in reasons["Orders.Doubled"], (
        "the refusal must name what it depends on, or it cannot be acted on"
    )


def test_refusal_travels_the_whole_chain_not_one_step():
    wb = _workbook(
        Table(
            name="Orders",
            columns=[
                _column("Sales"),
                _calc("A", "RANK(SUM([Sales]))"),
                _calc("B", "[A] * 2"),
                _calc("C", "[B] + 1"),
            ],
        )
    )
    _translate_calculations(wb)

    dax = _daxes(wb)
    assert dax["Orders.A"] is None
    assert dax["Orders.B"] is None
    assert dax["Orders.C"] is None, "refusal stopped one link short of the end"


def test_a_local_column_wins_over_a_same_named_measure_in_another_table():
    """Scope, with nothing refused anywhere.

    `Targets.Sales` converts perfectly well. `Orders.Profit Ratio` still means
    `Orders`'s own `Sales` column, because that is the field in scope where the
    formula was written. Resolving to the measure would emit DAX that reads a
    different table's number and looks entirely plausible.
    """
    wb = _workbook(
        Table(
            name="Orders",
            columns=[
                _column("Profit"),
                _column("Sales"),
                _calc("Profit Ratio", "sum([Profit])/sum([Sales])"),
            ],
        ),
        Table(
            name="Targets",
            columns=[_column("Quota"), _calc("Sales", "sum([Quota]) * 2")],
        ),
    )
    _translate_calculations(wb)

    dax = _daxes(wb)
    assert dax["Targets.Sales"] == "SUM('Targets'[Quota]) * 2"
    assert dax["Orders.Profit Ratio"] == "SUM('Orders'[Profit])/SUM('Orders'[Sales])"
    assert not wb.flags, [flag.reason for flag in wb.flags]


def test_a_parameter_reference_is_not_a_dependency():
    """A parameter is not a calculation and cannot be refused by one."""
    from t2pbi.core.graph import build
    from t2pbi.ir import Parameter

    wb = _workbook(
        Table(name="Orders", columns=[_column("Sales"), _calc("Scaled", "sum([Sales]) * [Rate]")])
    )
    wb.parameters = [
        Parameter(name="Rate", caption="Rate", datatype="real", default_value="1")
    ]
    graph, _ = build(wb)
    assert graph.edges["Orders.Scaled"] == frozenset()


# --- ordering ---------------------------------------------------------------


def _graph_of(*calcs: tuple[str, str]):
    from t2pbi.core.graph import build

    wb = _workbook(
        Table(
            name="Orders",
            columns=[_column("Sales"), *[_calc(name, formula) for name, formula in calcs]],
        )
    )
    return build(wb)[0]


def test_a_dependency_is_converted_before_what_depends_on_it():
    graph = _graph_of(
        ("C", "[B] + 1"), ("A", "sum([Sales])"), ("B", "[A] * 2")
    )
    ordered, cycled = graph.order()
    assert cycled == []
    assert ordered.index("Orders.A") < ordered.index("Orders.B")
    assert ordered.index("Orders.B") < ordered.index("Orders.C")


def test_the_order_does_not_depend_on_the_order_the_calcs_arrived_in():
    """Determinism: same workbook, same order, whatever the file listed first."""
    forward = _graph_of(("A", "sum([Sales])"), ("B", "sum([Sales]) * 2")).order()
    backward = _graph_of(("B", "sum([Sales]) * 2"), ("A", "sum([Sales])")).order()
    assert forward == backward


def test_a_cycle_is_refused_rather_than_ordered_arbitrarily():
    """Each member needs another member first, so no order exists.

    Emitting one of them anyway produces DAX that refers to itself - a model
    that fails when it is opened, which is the surprise this product exists to
    prevent.
    """
    wb = _workbook(
        Table(
            name="Orders",
            columns=[
                _column("Sales"),
                _calc("A", "[B] + 1"),
                _calc("B", "[A] + 1"),
            ],
        )
    )
    _translate_calculations(wb)

    dax = _daxes(wb)
    assert dax["Orders.A"] is None
    assert dax["Orders.B"] is None
    reasons = " ".join(flag.reason for flag in wb.flags)
    assert "refers to itself" in reasons
