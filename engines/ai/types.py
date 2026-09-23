"""What may be sent to a model, and what comes back.

`P4.1`, 07-ai-engine.md. The request type is the data-minimisation rule (§29)
written as a type rather than as a convention.

To translate `SUM([Revenue]) / SUM([Units])` a model needs the expression, the
schema of the fields it names, the rules that were tried, and why the
deterministic path refused. It does not need - and must never be able to
receive - the workbook, the other expressions, any row of data, a connection
string, or the file's name.

Those are the fields below and there are no others. `frozen=True` closes the
other half of it: a caller cannot attach an extra attribute at runtime and
smuggle something through. Enforcing this here means every future provider,
prompt and router inherits it without having to remember.
"""

from __future__ import annotations

from dataclasses import dataclass


class ProviderUnavailable(RuntimeError):
    """No model was reachable, so nothing was asked.

    Deliberately an exception and not a `None` return. Upstream, a `None` from
    `generate` becomes "the model had no suggestion for this" - a claim about
    the expression. The truth is "there was no model", a claim about the
    machine, and the two must not be reported as one.
    """


@dataclass(frozen=True)
class FieldSchema:
    """A field's shape. Never a value of it."""

    table: str
    name: str
    datatype: str


@dataclass(frozen=True)
class LLMRequest:
    """One expression and the minimum needed to reason about it."""

    operation: str
    source_platform: str
    target_platform: str
    #: The single expression under consideration. Never a second one.
    expression: str
    #: Only the fields this expression references.
    fields: tuple[FieldSchema, ...]
    #: Rule-pack ids relevant to the attempt, so the model sees what was tried.
    rule_ids: tuple[str, ...]
    #: Why the deterministic path refused - the actual question being asked.
    refusal_reason: str


@dataclass(frozen=True)
class LLMResponse:
    """Raw text from a model, and which model said it.

    Not parsed here. Turning this into a proposal - schema, then rules, then
    security - is the router's job (`P4.4`), and a provider that understood
    proposals would be a provider that could approve one.
    """

    text: str
    model: str
