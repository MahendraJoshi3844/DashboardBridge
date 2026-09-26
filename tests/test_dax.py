from t2pbi.core.dax import translate_formula


def test_simple_aggregation_divide():
    r = translate_formula("SUM([Sales]) / SUM([Quantity])", "Sales")
    assert r.dax == "SUM('Sales'[Sales]) / SUM('Sales'[Quantity])"
    assert r.reason is None


def test_if_then_else():
    r = translate_formula("IF [Sales] > 0 THEN 1 ELSE 0 END", "Sales")
    assert r.dax == "IF('Sales'[Sales] > 0, 1, 0)"


def test_zn_becomes_coalesce_zero():
    r = translate_formula("ZN([Sales])", "Sales")
    assert r.dax == "COALESCE('Sales'[Sales], 0)"


def test_avg_maps_to_average():
    r = translate_formula("AVG([Sales])", "Sales")
    assert r.dax == "AVERAGE('Sales'[Sales])"


def test_unsupported_running_sum_is_flagged_not_guessed():
    r = translate_formula("RUNNING_SUM(SUM([Sales]))", "Sales")
    assert r.dax is None
    assert "RUNNING_" in r.reason or "unsupported" in r.reason.lower()


def test_unknown_function_flagged():
    r = translate_formula("MAGIC([Sales])", "Sales")
    assert r.dax is None
    assert "MAGIC" in r.reason
