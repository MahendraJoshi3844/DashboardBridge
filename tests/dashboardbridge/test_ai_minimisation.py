"""Data minimisation in practice (`P4.5`), against a real converted workbook.

07-ai-engine.md, §29. To translate `SUM([Revenue]) / SUM([Units])` a model is
sent the expression, the schema of the fields it references, the rules that were
tried and why the deterministic path refused. Never the workbook, never other
expressions, never row data, never a connection string, never the file name.

`LLMRequest` already makes most of that impossible - it has nowhere to put a
workbook. What it cannot do on its own is stop a caller putting *all fifty-four
columns* in the `fields` tuple, which would be minimisation in shape only. So
this is tested against Superstore, where the difference between "the fields this
expression names" and "the fields the workbook has" is large enough to be
obvious.

These live outside `engines/ai` on purpose: extracting the pieces needs the
canonical model, and the AI layer is not allowed to import it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from engines.conversion.ai_requests import policy_for, request_for
from engines.conversion.run import convert_tableau_to_powerbi

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def converted():
    with tempfile.TemporaryDirectory(prefix="dbb-minimise-") as tmp:
        outcome = convert_tableau_to_powerbi(
            (FIXTURES / "clashes.twb").read_bytes(), Path(tmp) / "p", "Clashes"
        )
    return outcome


def _refused(model):
    return [
        column
        for datasource in model.datasources or []
        for table in datasource.tables or []
        for column in table.columns or []
        if column.expression and not column.translation
    ]


def test_there_is_something_refused_to_ask_about(converted):
    assert _refused(converted.model), "the fixture no longer refuses anything"


def test_the_request_carries_only_the_fields_the_expression_names(converted):
    """The heart of §29.

    `Returns.Return Rate` is `[Quantity] * 1.0`. It names one field. The
    workbook has three tables and a dozen columns, and the model is sent one.
    """
    column = next(c for c in _refused(converted.model) if c.id.endswith("Return Rate"))
    request = request_for(converted.model, column.id, "depends on Quantity")

    assert [f.name for f in request.fields] == ["Quantity"]
    assert request.expression == column.expression.source_text


def test_no_other_expression_travels_with_it(converted):
    """One expression per request. A second one is a second conversation."""
    column = next(c for c in _refused(converted.model) if c.id.endswith("Return Rate"))
    request = request_for(converted.model, column.id, "reason")

    others = [
        c.expression.source_text
        for c in _refused(converted.model) + list(_translated(converted.model))
        if c.id != column.id
    ]
    for other in others:
        assert other not in request.expression


def _translated(model):
    return [
        column
        for datasource in model.datasources or []
        for table in datasource.tables or []
        for column in table.columns or []
        if column.expression and column.translation
    ]


def test_the_request_names_nothing_about_the_file_it_came_from(converted):
    """No file name, no path, no connection string (§29)."""
    column = next(c for c in _refused(converted.model) if c.id.endswith("Return Rate"))
    request = request_for(converted.model, column.id, "reason")

    blob = repr(request).lower()
    for leak in ("clashes", ".twb", "sqlserver", "c:\\", "/tmp", "http"):
        assert leak not in blob, f"the request mentions {leak!r}"


def test_a_field_resolves_in_its_own_table_first(converted):
    """The scoping rule from `P3.2`, applied to what the model is told.

    `Orders` and `Returns` both have something called `Quantity`. Sending the
    wrong table's schema would have the model translate against a column that
    is not the one the expression means.
    """
    column = next(c for c in _refused(converted.model) if c.id.endswith("Return Rate"))
    request = request_for(converted.model, column.id, "reason")
    assert [f.table for f in request.fields] == ["Returns"]


def test_building_the_same_request_twice_gives_the_same_request(converted):
    column = _refused(converted.model)[0]
    assert request_for(converted.model, column.id, "r") == request_for(
        converted.model, column.id, "r"
    )


def test_asking_about_a_column_that_is_not_there_is_refused(converted):
    with pytest.raises(KeyError):
        request_for(converted.model, "Nowhere.Nothing", "reason")


# --- the policy -------------------------------------------------------------


def test_the_policy_permits_exactly_what_the_model_defines(converted):
    """`P4.4` checks proposals against this, so it has to be the real thing."""
    policy = policy_for(converted.model)

    assert "Orders[Sales]" in policy.allowed_references
    assert "Returns[Return Count]" in policy.allowed_references
    assert "Orders[Nonexistent]" not in policy.allowed_references


def test_the_policy_permits_only_functions_the_rule_pack_knows(converted):
    """Unknown-good is not known-bad, and only one of them ships."""
    policy = policy_for(converted.model)

    assert "SUM" in policy.allowed_functions
    assert "DISTINCTCOUNT" in policy.allowed_functions
    assert "EARLIER" not in policy.allowed_functions


def test_the_policy_carries_no_model_object(converted):
    """It is a flat set of names, so `engines/ai` still cannot see a workbook."""
    policy = policy_for(converted.model)
    assert isinstance(policy.allowed_references, frozenset)
    assert all(isinstance(name, str) for name in policy.allowed_references)
