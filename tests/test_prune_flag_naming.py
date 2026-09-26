"""A pruned field well must name the field the way Tableau does.

`_bind_to_emitted` drops a binding whose column was never written and reports
it. The report it produces is customer-facing — it reaches the migration report
and the results screen — so the name in it has to be the one a person will
recognise in the source.

A Tableau calculation carries an internal `name` (`Calculation_4120925132203686`)
and a `caption` (`Rank over 3`). A shelf may reference either. Reporting the
internal one asks a reader to find a field by an id that appears nowhere in
their workbook, which is the parser's vocabulary standing in for the source's.
"""

from __future__ import annotations

from t2pbi.core.emit.pbip import _bind_to_emitted
from t2pbi.core.mapping import FieldRef, PBIVisual
from t2pbi.ir import Column, DataSource, Table, Workbook


def _workbook_with_a_refused_calc() -> Workbook:
    """One calculation, captioned, that translation refused (`dax` is None)."""
    refused = Column(
        name="Calculation_4120925132203686",
        caption="Rank over 3",
        datatype="real",
        role="measure",
        formula="RANK(SUM([Sales]))",
    )
    plain = Column(name="Sales", datatype="real", role="measure")
    return Workbook(
        datasources=[
            DataSource(
                name="ds",
                connection="none",
                tables=[Table(name="Orders", columns=[refused, plain])],
            )
        ],
    )


def _prune(wb: Workbook, column: str) -> list:
    visual = PBIVisual(
        name="Sheet 1",
        visual_type="clusteredBarChart",
        category=[FieldRef(table="Orders", column=column)],
        values=[],
        legend=[],
    )
    _bind_to_emitted(wb, [visual])
    return wb.flags


def test_a_pruned_field_is_named_by_its_caption_not_its_internal_id():
    wb = _workbook_with_a_refused_calc()
    flags = _prune(wb, "Calculation_4120925132203686")

    assert len(flags) == 1, "the dropped binding must be reported"
    flag = flags[0]
    assert "Rank over 3" in flag.reason
    assert "Calculation_4120925132203686" not in flag.reason
    assert "Calculation_4120925132203686" not in flag.item


def test_a_field_the_workbook_does_not_know_is_reported_as_it_was_named():
    """No caption to substitute means the shelf's own word, not a blank.

    Inventing a friendlier name for a field the model has never heard of would
    be a guess, and the reader needs the string that is actually in the shelf.
    """
    wb = _workbook_with_a_refused_calc()
    flags = _prune(wb, "Nowhere")

    assert len(flags) == 1
    assert "Nowhere" in flags[0].reason
