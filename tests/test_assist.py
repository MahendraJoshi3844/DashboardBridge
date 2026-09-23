"""Local AI assist: the offline guarantee, and the shape of what we send.

These cover the pure, reviewable parts. The network call itself is exercised only
when a local runtime is actually running, which CI cannot assume.
"""

from engines.t2pbi import assist


def test_assist_only_ever_targets_loopback():
    """The offline promise in code: no hostname but the local machine."""
    assert assist._HOST in {"127.0.0.1", "localhost"}


def test_runtime_absence_is_reported_not_raised():
    assert isinstance(assist.runtime_available(timeout_s=0.05), bool)


def test_no_suggestion_when_no_local_runtime_is_listening():
    if assist.runtime_available():
        return  # a runtime is up on this machine; nothing to assert
    assert assist.suggest_for("Forecast", "[Sales]*2", "ambiguous", "Orders") is None


def test_prompt_carries_the_field_its_formula_and_the_refusal_reason():
    prompt = assist.build_prompt(
        "Sales Forecast",
        "[Sales]*(1+[Rate])",
        "Mixes a row-level column with a parameter.",
        "Orders",
    )
    assert "Sales Forecast" in prompt
    assert "[Sales]*(1+[Rate])" in prompt
    assert "row-level column" in prompt
    assert "Orders" in prompt


def test_prompt_contains_only_the_one_field_never_the_workbook():
    """Assist sends a single field, so a local model never sees the whole model."""
    prompt = assist.build_prompt("A", "[X]+1", "why", "T")
    assert "[Y]" not in prompt and "Customer" not in prompt
    assert prompt.count("Tableau formula:") == 1


def test_fenced_model_output_is_unwrapped():
    assert assist._clean('```dax\nSUM(Orders[Sales])\n```') == "SUM(Orders[Sales])"


def test_dax_prefix_is_stripped():
    assert assist._clean("DAX: SUM(Orders[Sales])") == "SUM(Orders[Sales])"
