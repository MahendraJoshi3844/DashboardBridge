"""Decoding Tableau's encoded shelf field references.

Real Tableau writes shelf refs as ``[datasource].[agg:Field:role-kind]``, not as
plain field names. Decoding these wrong silently binds every visual to a
non-existent column, so these tests pin the encoding rules directly.
"""

from t2pbi.core.parse.worksheets import decode_shelf_ref, parse_shelf_expression


def test_decodes_aggregated_measure_ref():
    ref = decode_shelf_ref("[federated.10nnk8d].[sum:Sales:qk]")
    assert ref.field == "Sales"
    assert ref.aggregation == "sum"
    assert ref.datasource == "federated.10nnk8d"
    assert ref.resolvable


def test_decodes_unaggregated_dimension_ref():
    ref = decode_shelf_ref("[federated.10nnk8d].[none:Customer Name:nk]")
    assert ref.field == "Customer Name"
    assert ref.aggregation is None
    assert ref.resolvable


def test_decodes_date_part_ref_and_keeps_the_part():
    ref = decode_shelf_ref("[federated.10nnk8d].[yr:Order Date:ok]")
    assert ref.field == "Order Date"
    assert ref.date_part == "yr"
    assert ref.resolvable


def test_decodes_calculated_field_ref_by_internal_name():
    ref = decode_shelf_ref("[federated.0a01cod].[usr:Calculation_4120925132203686:ok]")
    assert ref.field == "Calculation_4120925132203686"
    assert ref.resolvable


def test_plain_unencoded_ref_passes_through():
    ref = decode_shelf_ref("[federated.sales].[Order Date]")
    assert ref.field == "Order Date"
    assert ref.aggregation is None
    assert ref.resolvable


def test_measure_names_is_not_a_resolvable_field():
    ref = decode_shelf_ref("[federated.10nnk8d].[:Measure Names]")
    assert not ref.resolvable


def test_multiple_values_is_not_a_resolvable_field():
    ref = decode_shelf_ref("[federated.10nnk8d].[Multiple Values]")
    assert not ref.resolvable


def test_nested_table_calc_over_object_id_is_not_resolvable():
    raw = "[federated.x].[pcto:cnt:Orders_6D2EF74F348B46BDA976A7AEEA6FB5C9:qk:1]"
    ref = decode_shelf_ref(raw)
    assert not ref.resolvable


def test_object_id_join_key_is_not_resolvable():
    ref = decode_shelf_ref("[federated.x].[__tableau_internal_object_id__]")
    assert not ref.resolvable


def test_shelf_expression_yields_every_operand_in_order():
    expr = "([federated.x].[none:Region:nk] * [federated.x].[sum:Sales:qk])"
    refs = parse_shelf_expression(expr)
    assert [r.field for r in refs] == ["Region", "Sales"]
