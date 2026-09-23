"""The validation gauntlet (`P4.4`). Nothing reaches a person without passing it.

07-ai-engine.md:

    LLM output
      → schema validation      shape and types
      → rule validation        does the expression use only known-good constructs?
      → security validation    no execution, no I/O, no injection artefacts
      → proposal

A failure at any stage discards the proposal. Discards, not downgrades: there is
no "show it anyway with a warning", because a warning next to a plausible
expression is read by exactly the people who are in a hurry.

## Why the middle stage is the one that matters

Malformed output is harmless - it fails to parse and everyone notices. The
dangerous output is a syntactically perfect expression referencing a table that
does not exist: it reads correctly, survives review, and fails when someone opens
the model weeks later. So every name in the expression is checked against the
names the target model actually has, before a person sees it.

## What this module is not given

Not the canonical model - `Policy` carries a flat set of permitted names. Same
reasoning as `LLMRequest`: the AI layer cannot be handed a workbook, so it is
handed the answer to the only question it needs to ask. It keeps `engines/ai`
free of the target model's types, which a boundary test enforces.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from enum import Enum

from dashboardbridge_contracts import AIProposal
from pydantic import BaseModel, Field, ValidationError

from engines.ai.types import LLMRequest

#: Deterministic proposal ids. A random uuid4 would make two identical runs
#: produce different reports, which this project treats as a defect rather than
#: a detail (see `emit` and the rule pack for the same rule).
_PROPOSAL_NAMESPACE = uuid.UUID("8f4e1a02-1f2b-4c7e-9a4b-2d3c5e6f7a8b")

#: `Table[Column]` and bare `Table` references inside a DAX expression.
_QUALIFIED_REF = re.compile(r"'?([A-Za-z_][\w ]*)'?\s*\[([^\[\]]+)\]")
#: A function call: a name immediately followed by `(`.
_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_.]*)\s*\(")

#: Things that are never part of a translated expression, and each of which
#: means something specific went wrong.
_SECURITY_MARKERS = (
    ("://", "a URL"),
    ("<<<USER-DATA", "the prompt's own fence, echoed back"),
    ("<<<END-USER-DATA", "the prompt's own fence, echoed back"),
    ("# SYSTEM INSTRUCTIONS", "the system prompt, echoed back"),
    ("# REFERENCE DATA", "the reference region, echoed back"),
    ("\\Windows", "a filesystem path"),
    ("/etc/", "a filesystem path"),
    ("EXECUTE ", "an execution verb"),
    ("EVALUATE ", "a query, not an expression"),
)


class Rejection(str, Enum):
    """Which stage discarded it. Never collapsed into a boolean."""

    NOT_JSON = "not_json"
    SCHEMA = "schema"
    WRONG_OPERATION = "wrong_operation"
    UNKNOWN_REFERENCE = "unknown_reference"
    DISALLOWED_FUNCTION = "disallowed_function"
    SECURITY = "security"
    LOW_CONFIDENCE = "low_confidence"


@dataclass(frozen=True)
class Policy:
    """What this target model permits, and where the confidence lines sit."""

    #: `"Orders"` and `"Orders[Revenue]"`. Flat strings, never the model.
    allowed_references: frozenset[str]
    allowed_functions: frozenset[str]
    #: 07-ai-engine.md. `preselect` is §65's `auto_accept`, reinterpreted:
    #: it moves the radio button and a person still presses it (ADR-007).
    preselect: float = 0.95
    review_required: float = 0.80
    reject_below: float = 0.60


@dataclass(frozen=True)
class Vetted:
    """The verdict. Exactly one of `proposal` and `rejection` is set."""

    proposal: AIProposal | None
    rejection: Rejection | None
    reason: str


class _Answer(BaseModel):
    """The shape the prompt asked for. Extra keys are a failed instruction."""

    model_config = {"extra": "forbid"}

    operation: str
    source_expression: str
    target_expression: str
    explanation: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    assumptions: list[str] = Field(default_factory=list)
    requires_review: bool = True


def _rejected(rejection: Rejection, reason: str) -> Vetted:
    return Vetted(proposal=None, rejection=rejection, reason=reason)


def vet(
    raw: str,
    request: LLMRequest,
    policy: Policy,
    *,
    model: str = "",
    prompt_version: int = 0,
) -> Vetted:
    """Run the gauntlet. Returns a proposal only if every stage passed."""
    # --- shape -------------------------------------------------------------
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _rejected(
            Rejection.NOT_JSON,
            "The model did not return JSON. Only the agreed shape is accepted; "
            "reading an expression out of prose would mean guessing where it "
            "started and ended.",
        )
    try:
        answer = _Answer.model_validate(parsed)
    except ValidationError as exc:
        return _rejected(
            Rejection.SCHEMA,
            f"The model's answer does not match the agreed shape: {exc.error_count()} "
            "problem(s). Nothing was filled in for it.",
        )

    if answer.operation != request.operation:
        return _rejected(
            Rejection.WRONG_OPERATION,
            f"The model answered {answer.operation!r} when it was asked for "
            f"{request.operation!r}.",
        )

    expression = answer.target_expression.strip()

    # --- security ----------------------------------------------------------
    # Before the rule stage, because an expression carrying a URL or an echoed
    # system prompt is not a malformed translation - it is not a translation.
    for marker, what in _SECURITY_MARKERS:
        if marker.lower() in expression.lower():
            return _rejected(
                Rejection.SECURITY,
                f"The proposed expression contains {what}, which no translated "
                "expression ever does.",
            )

    # --- rules -------------------------------------------------------------
    unknown = _unknown_references(expression, policy.allowed_references)
    if unknown:
        return _rejected(
            Rejection.UNKNOWN_REFERENCE,
            f"The proposed expression references {', '.join(unknown)}, which the "
            "produced model does not define. It would parse and then fail when "
            "someone opened the report.",
        )

    disallowed = sorted(
        {
            name.upper()
            for name in _CALL.findall(expression)
            if name.upper() not in policy.allowed_functions
        }
    )
    if disallowed:
        return _rejected(
            Rejection.DISALLOWED_FUNCTION,
            f"The proposed expression uses {', '.join(disallowed)}, which is not "
            "in the set of functions this converter knows to be equivalent.",
        )

    # --- confidence --------------------------------------------------------
    if answer.confidence < policy.reject_below:
        return _rejected(
            Rejection.LOW_CONFIDENCE,
            f"The model reported {answer.confidence:.2f} confidence, below the "
            f"{policy.reject_below:.2f} floor. Discarded rather than shown.",
        )

    return Vetted(
        proposal=AIProposal(
            proposal_id=uuid.uuid5(_PROPOSAL_NAMESPACE, f"{request.expression}\n{expression}"),
            operation=request.operation,
            # Ours, not the model's. A model that rewrote the question does not
            # get to be recorded as having answered a different one.
            source_expression=request.expression,
            target_expression=expression,
            explanation=answer.explanation,
            confidence=answer.confidence,
            assumptions=list(answer.assumptions),
            # Never read from the answer: the model does not get to mark its own
            # work as settled.
            requires_review=True,
            preselected=answer.confidence >= policy.preselect,
            model=model,
            prompt_version=prompt_version,
        ),
        rejection=None,
        reason="",
    )


def _unknown_references(expression: str, allowed: frozenset[str]) -> list[str]:
    """Every `Table[Column]` in the expression that the model does not define."""
    unknown: list[str] = []
    for table, column in _QUALIFIED_REF.findall(expression):
        reference = f"{table.strip()}[{column.strip()}]"
        if reference not in allowed and reference not in unknown:
            unknown.append(reference)
    return unknown
