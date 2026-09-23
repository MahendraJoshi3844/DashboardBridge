"""Structural requirements a semantic model must meet to load at all.

A TMDL table with no partition, or a column whose sourceColumn names something
the partition does not produce, makes Power BI Desktop reject the whole model —
so none of the rest of the conversion is worth anything without these.
"""

import pytest

from engines.t2pbi.core.emit.params import param_table_tmdl
from engines.t2pbi.core.emit.tmdl import table_tmdl
from engines.t2pbi.ir import Column, Parameter, Severity, Table, Workbook


def _orders() -> Table:
    return Table(
        name="Orders",
        columns=[
            Column(name="Order ID", datatype="string", role="dimension"),
            Column(name="Sales", datatype="real", role="measure"),
        ],
    )


def test_every_table_declares_a_partition():
    tmdl = table_tmdl(_orders())
    assert "partition" in tmdl


def test_partition_declares_every_column_so_the_schema_survives():
    tmdl = table_tmdl(_orders())
    assert "Order ID" in tmdl
    assert "Sales" in tmdl


def test_unconnected_table_is_flagged_so_the_gap_is_never_silent():
    wb = Workbook()
    table_tmdl(_orders(), workbook=wb, datasource="Superstore")
    manual = [f for f in wb.flags if f.severity == Severity.MANUAL]
    assert any("Orders" in f.item for f in manual)


@pytest.mark.parametrize(
    "param",
    [
        Parameter(
            name="Rate", caption="Rate", datatype="real", default_value="0.5",
            kind="range", min_value="0.0", max_value="1.0", step="0.1",
        ),
        Parameter(
            name="Sort", caption="Sort", datatype="string", default_value='"A"',
            kind="list", members=['"A"', '"B"'],
        ),
    ],
    ids=["range", "list"],
)
def test_what_if_column_reads_the_column_its_partition_produces(param):
    tmdl = param_table_tmdl(param)
    # GENERATESERIES and a {...} table constructor both produce a column
    # literally named "Value"; naming anything else breaks the model.
    assert "sourceColumn: Value" in tmdl
    assert "sourceColumn: [" not in tmdl


def test_unbounded_range_parameter_does_not_pin_its_max_to_the_default():
    unbounded = Parameter(
        name="Base Salary", caption="Base Salary", datatype="integer",
        default_value="50000", kind="range", min_value="0", step="1000",
    )
    tmdl = param_table_tmdl(unbounded)
    assert "GENERATESERIES(0, 50000, 1000)" not in tmdl


def test_unbounded_range_parameter_is_flagged():
    wb = Workbook()
    unbounded = Parameter(
        name="Base Salary", caption="Base Salary", datatype="integer",
        default_value="50000", kind="range", min_value="0", step="1000",
    )
    param_table_tmdl(unbounded, workbook=wb)
    assert any("Base Salary" in f.item for f in wb.flags)
