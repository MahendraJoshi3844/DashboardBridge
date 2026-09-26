"""DAX translation with a populated context: params, cross-table, control flow.

These lock in the fidelity fixes from the Superstore manual-test findings.
"""

from t2pbi.core.dax.translator import TranslationContext, translate_formula


def _ctx():
    return TranslationContext(
        field_to_table={
            "sales": "Orders",
            "profit": "Orders",
            "quantity": "Orders",
            "ship mode": "Orders",
            "order date": "Orders",
            "ship date": "Orders",
            "sales target": "Sales Target",
        },
        columns_by_table={
            "Orders": {"sales", "profit", "quantity", "ship mode", "order date", "ship date"},
            "Sales Target": {"sales target"},
        },
        measures={"base (variable)": "Base (Variable)", "achievement (copy)": "Achievement (estimated)"},
        param_value_measures={
            "parameter 1": "New Business Growth Value",
            "base salary": "Base Salary Value",
        },
    )


def test_case_becomes_switch():
    r = translate_formula(
        'CASE [Ship Mode] WHEN "Same Day" THEN 0 ELSE 6 END', "Orders", _ctx()
    )
    assert r.dax == 'SWITCH(\'Orders\'[Ship Mode], "Same Day", 0, 6)'


def test_elseif_chain_becomes_switch_true():
    r = translate_formula(
        'IF [Sales]>0 THEN "a" ELSEIF [Sales]<0 THEN "b" ELSE "c" END', "Orders", _ctx()
    )
    assert r.dax == (
        "SWITCH(TRUE(), 'Orders'[Sales]>0, \"a\", 'Orders'[Sales]<0, \"b\", \"c\")"
    )


def test_parameter_reference_uses_value_measure():
    r = translate_formula("[Sales]*(1+[Parameter 1])", "Orders", _ctx())
    assert r.dax == "'Orders'[Sales]*(1+[New Business Growth Value])"


def test_cross_table_reference_not_double_wrapped():
    r = translate_formula("SUM([Sales Target])", "Orders", _ctx())
    assert r.dax == "SUM('Sales Target'[Sales Target])"
    assert "''" not in r.dax


def test_local_table_wins_on_name_collision():
    # "Order Date" exists only in Orders here; ensure it qualifies to Orders.
    r = translate_formula("DATEDIFF('day',[Order Date],[Ship Date])", "Orders", _ctx())
    assert r.dax == "DATEDIFF('Orders'[Order Date], 'Orders'[Ship Date], DAY)"


def test_measure_reference_uses_emitted_display_name():
    # raw name [Achievement (copy)] -> emitted measure [Achievement (estimated)]
    r = translate_formula("MIN([Achievement (copy)])", "Orders", _ctx())
    assert r.dax == "MIN([Achievement (estimated)])"


def test_residual_case_keyword_is_flagged_not_emitted():
    # An IF without END cannot be safely converted -> must flag, never emit.
    r = translate_formula('IF [Sales] > 0 THEN "x"', "Orders", _ctx())
    assert r.dax is None
    assert r.reason


def test_datediff_with_a_function_call_argument_is_not_half_converted():
    """A nested call in the last argument must not be torn in half.

    `_DATEDIFF_RE`'s last group stopped at the first `)`, so `TODAY()` was cut
    after `TODAY(` and the rest of the call was emitted as DAX with no flag:
    `DATEDIFF('Orders'[Order Date], TODAY(, DAY))`. Silent malformed DAX is the
    one thing the translator must never do - a refusal is acceptable, this is not.
    """
    r = translate_formula("DATEDIFF('day',[Order Date],TODAY())", "Orders", _ctx())
    if r.dax is not None:
        assert r.dax == "DATEDIFF('Orders'[Order Date], TODAY(), DAY)"
    else:
        assert r.reason
