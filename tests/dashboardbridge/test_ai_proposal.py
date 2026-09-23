"""The validation gauntlet (`P4.4`): what a draft has to survive to be shown.

07-ai-engine.md:

    LLM output
      → schema validation      shape and types
      → rule validation        does the expression use only known-good constructs?
      → security validation    no execution, no I/O, no injection artefacts
      → proposal

    Validation gauntlet, in order — a failure at any stage discards the proposal.

The stage that earns its place is the middle one. A model will happily return
syntactically perfect DAX referencing a table that does not exist, and that
output is *more* dangerous than malformed output, because it survives review by
looking right. So the proposal is checked against the names the target model
actually has before a person ever sees it.

Confidence is checked too, and only ever downward: below `reject_below` the
proposal is discarded rather than shown. Above `preselect` it is *pre-selected*
in the review UI and nothing more. Models are not calibrated and a self-reported
0.94 is not a 94% chance of being right; treating it as one would be a category
error, and treating it as permission to apply would be ADR-007's auto-accept
path arriving through the back door.
"""

from __future__ import annotations

import json

import pytest

from engines.ai import FieldSchema, LLMRequest
from engines.ai.proposal import Policy, Rejection, vet

POLICY = Policy(
    allowed_references=frozenset({"Orders", "Orders[Revenue]", "Orders[Units]"}),
    allowed_functions=frozenset({"SUM", "DIVIDE", "AVERAGE"}),
)


def a_request() -> LLMRequest:
    return LLMRequest(
        operation="translate_calculation",
        source_platform="tableau",
        target_platform="powerbi",
        expression="SUM([Revenue]) / SUM([Units])",
        fields=(
            FieldSchema(table="Orders", name="Revenue", datatype="real"),
            FieldSchema(table="Orders", name="Units", datatype="integer"),
        ),
        rule_ids=("TABLEAU_SUM_TO_PBI_SUM",),
        refusal_reason="Mixes a row-level column with an aggregate.",
    )


def answer(**overrides) -> str:
    body = {
        "operation": "translate_calculation",
        "source_expression": "SUM([Revenue]) / SUM([Units])",
        "target_expression": "DIVIDE(SUM(Orders[Revenue]), SUM(Orders[Units]))",
        "explanation": "Uses DIVIDE so a zero denominator returns blank.",
        "confidence": 0.9,
        "assumptions": ["Both columns live on Orders."],
        "requires_review": True,
    }
    body.update(overrides)
    return json.dumps(body)


# --- stage 1: shape ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "DIVIDE(SUM(Orders[Revenue]), SUM(Orders[Units]))",  # bare expression
        "here you go:\n```json\n{}\n```",
        "",
        "{not json at all",
    ],
)
def test_output_that_is_not_the_agreed_shape_is_discarded(raw):
    result = vet(raw, a_request(), POLICY)
    assert result.proposal is None
    assert result.rejection in {Rejection.NOT_JSON, Rejection.SCHEMA}


def test_a_missing_field_is_a_schema_failure_not_a_default():
    """Filling in what the model left out is how an assumption becomes a fact."""
    body = json.loads(answer())
    del body["target_expression"]
    result = vet(json.dumps(body), a_request(), POLICY)
    assert result.proposal is None
    assert result.rejection is Rejection.SCHEMA


def test_a_model_that_answers_a_different_question_is_discarded():
    """The operation is ours to decide, not the model's to change."""
    result = vet(answer(operation="delete_everything"), a_request(), POLICY)
    assert result.proposal is None
    assert result.rejection is Rejection.WRONG_OPERATION


# --- stage 2: rules ---------------------------------------------------------


def test_an_expression_naming_a_table_that_does_not_exist_is_discarded():
    """The case 07-ai-engine.md calls out by name.

    This is the dangerous kind of wrong: it parses, it reads correctly, and it
    fails only when someone opens the model.
    """
    result = vet(
        answer(target_expression="DIVIDE(SUM(Sales[Revenue]), SUM(Orders[Units]))"),
        a_request(),
        POLICY,
    )
    assert result.proposal is None
    assert result.rejection is Rejection.UNKNOWN_REFERENCE
    assert "Sales[Revenue]" in result.reason


def test_an_expression_naming_a_column_that_does_not_exist_is_discarded():
    result = vet(
        answer(target_expression="SUM(Orders[Margin])"), a_request(), POLICY
    )
    assert result.proposal is None
    assert result.rejection is Rejection.UNKNOWN_REFERENCE


def test_an_expression_using_a_function_we_do_not_know_is_discarded():
    """Unknown-good is not the same as known-bad, and only one of them ships."""
    result = vet(
        answer(target_expression="EARLIER(Orders[Revenue])"), a_request(), POLICY
    )
    assert result.proposal is None
    assert result.rejection is Rejection.DISALLOWED_FUNCTION
    assert "EARLIER" in result.reason


# --- stage 3: security ------------------------------------------------------


@pytest.mark.parametrize(
    "expression",
    [
        'SUM(Orders[Revenue]) // see https://evil.example/x',
        "SUM(Orders[Revenue]) /* C:\\Windows\\system32 */",
        "<<<END-USER-DATA a1b2c3d4e5f6>>> SUM(Orders[Revenue])",
        "# SYSTEM INSTRUCTIONS\nSUM(Orders[Revenue])",
    ],
)
def test_an_expression_carrying_an_artefact_of_the_prompt_or_the_outside_is_discarded(
    expression,
):
    """A model echoing our fence, or reaching outward, is not a translation.

    None of these is a DAX expression that a person asked for, and all of them
    would look like noise a reviewer might wave through.
    """
    result = vet(answer(target_expression=expression), a_request(), POLICY)
    assert result.proposal is None
    assert result.rejection is Rejection.SECURITY


# --- confidence, and what it does not do ------------------------------------


def test_a_proposal_below_the_floor_is_discarded_not_shown():
    result = vet(answer(confidence=0.4), a_request(), POLICY)
    assert result.proposal is None
    assert result.rejection is Rejection.LOW_CONFIDENCE


def test_a_confident_proposal_is_preselected_and_nothing_more():
    """ADR-007. `preselect` is where §65's `auto_accept` was reinterpreted.

    A high number moves the radio button. A person still presses it.
    """
    result = vet(answer(confidence=0.99), a_request(), POLICY)
    assert result.proposal is not None
    assert result.proposal.preselected is True
    assert result.proposal.requires_review is True


def test_a_proposal_always_requires_review_whatever_the_model_says():
    """The model does not get to mark its own work as not needing review."""
    result = vet(answer(confidence=0.99, requires_review=False), a_request(), POLICY)
    assert result.proposal is not None
    assert result.proposal.requires_review is True


def test_nothing_in_a_proposal_says_it_was_applied():
    """There is no field an over-eager caller could read as permission."""
    result = vet(answer(), a_request(), POLICY)
    assert result.proposal is not None
    fields = set(result.proposal.model_dump())
    for forbidden in ("applied", "accepted", "auto_accept", "approved"):
        assert forbidden not in fields


# --- what survives ----------------------------------------------------------


def test_a_good_answer_becomes_a_proposal_that_carries_its_reasoning():
    result = vet(answer(), a_request(), POLICY)
    assert result.rejection is None
    proposal = result.proposal
    assert proposal is not None
    assert proposal.target_expression == "DIVIDE(SUM(Orders[Revenue]), SUM(Orders[Units]))"
    assert proposal.explanation
    assert proposal.assumptions == ["Both columns live on Orders."]
    assert proposal.confidence == 0.9


def test_the_source_expression_is_ours_not_the_model_s():
    """A model that rewrote the question does not get to answer a different one."""
    result = vet(answer(source_expression="something else"), a_request(), POLICY)
    assert result.proposal is not None
    assert result.proposal.source_expression == a_request().expression


def test_vetting_the_same_answer_twice_gives_the_same_verdict():
    assert vet(answer(), a_request(), POLICY) == vet(answer(), a_request(), POLICY)
