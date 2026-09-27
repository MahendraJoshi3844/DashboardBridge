"""A Sum of a column is a field in its well, not an empty reference.

Power BI Desktop writes `SUM(Sales)` in a visual as an `Aggregation` wrapped
around the `Column`, and the Tableau engine now writes it the same way. Both
readers of generated PBIR - validation's and the Power BI adapter's - read only
`Column` and `Measure`, so a summed field looked as though it never crossed,
and the refusal-integrity check reported a field that was there.
"""

from __future__ import annotations

import json

from engines.adapters.powerbi import _binding
from engines.validation.target import _parse_visual

SUM_OF_SALES = {
    "Aggregation": {
        "Expression": {"Column": {"Expression": {"SourceRef": {"Entity": "Orders"}}, "Property": "Sales"}},
        "Function": 0,
    }
}


def test_validation_reads_a_summed_column_as_that_column():
    raw = json.dumps({"visual": {"visualType": "clusteredColumnChart", "query": {"queryState": {
        "Y": {"projections": [{"field": SUM_OF_SALES, "queryRef": "Sum(Orders.Sales)"}]}}}}})
    visual = _parse_visual(raw)
    assert [(b.well, b.table, b.column) for b in visual.bindings] == [("Y", "Orders", "Sales")]


def test_the_power_bi_adapter_reads_a_summed_column_as_that_column():
    from dashboardbridge_contracts.enums import BindingRole

    role = next(iter(BindingRole))
    binding = _binding(SUM_OF_SALES, role)
    assert binding is not None and "Sales" in binding.model_dump_json()
