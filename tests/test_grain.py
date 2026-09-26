"""Grain classification: is a Tableau calc a DAX measure or a calculated column?

Tableau decides aggregation at the shelf; Power BI decides it at definition time.
Getting this wrong emits DAX that will not validate — a bare column reference in a
measure, or an aggregation wrapped around a measure. When the intended grain is
genuinely ambiguous we must refuse to convert rather than guess.
"""

from t2pbi.core.dax.grain import classify_calc

# alias -> grain for calcs already classified; a parameter reads like an
# aggregate, because it takes its value from a slicer rather than from a row.
NO_CALCS: dict[str, str] = {}
NO_PARAMS: set[str] = set()


def test_fully_aggregated_formula_is_a_measure():
    v = classify_calc("SUM([Profit]) / SUM([Sales])", NO_CALCS, NO_PARAMS)
    assert v.grain == "aggregate"


def test_row_level_formula_is_a_calculated_column():
    v = classify_calc("DATEDIFF('day',[Order Date],[Ship Date])", NO_CALCS, NO_PARAMS)
    assert v.grain == "row"


def test_bare_column_reference_is_a_calculated_column():
    v = classify_calc("[Sales]", NO_CALCS, NO_PARAMS)
    assert v.grain == "row"


def test_constant_only_formula_is_a_measure():
    v = classify_calc('"Total Sales:"', NO_CALCS, NO_PARAMS)
    assert v.grain == "aggregate"


def test_parameter_only_formula_is_a_measure():
    v = classify_calc("[Base Salary]", NO_CALCS, {"base salary"})
    assert v.grain == "aggregate"


def test_aggregating_a_calculated_column_is_a_measure():
    v = classify_calc("AVG([Achievement])", {"achievement": "row"}, NO_PARAMS)
    assert v.grain == "aggregate"


def test_aggregating_a_measure_is_refused():
    v = classify_calc("MIN([Base Variable])", {"base variable": "aggregate"}, NO_PARAMS)
    assert v.grain is None
    assert "aggregat" in v.reason.lower()


def test_row_level_column_mixed_with_a_parameter_is_refused():
    # Tableau applies the shelf aggregation; Power BI cannot infer which one.
    v = classify_calc("([Commission Rate]*[Sales])/100", NO_CALCS, {"commission rate"})
    assert v.grain is None
    assert "aggregation" in v.reason.lower()


def test_row_level_reference_to_a_measure_is_refused():
    v = classify_calc("[Sales] * [Some Measure]", {"some measure": "aggregate"}, NO_PARAMS)
    assert v.grain is None


def test_conditional_over_calculated_columns_stays_a_column():
    grains = {"days actual": "row", "days scheduled": "row"}
    v = classify_calc(
        'IF [Days Actual] > [Days Scheduled] THEN "Late" ELSE "Early" END',
        grains,
        NO_PARAMS,
    )
    assert v.grain == "row"


def test_bracketed_field_name_containing_a_function_word_is_not_an_aggregation():
    v = classify_calc("[Sum of Things]", NO_CALCS, NO_PARAMS)
    assert v.grain == "row"
