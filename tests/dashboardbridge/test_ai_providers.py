"""The provider layer (`P4.1`): everything that can reach a model, and nothing else.

07-ai-engine.md. Three properties are load-bearing and are what these tests are
for. They are all about what the layer *cannot* do, because every one of them is
a promise the product sells and none of them is visible when it breaks:

* **A local provider is loopback-only.** Workbook content never leaves the
  machine. A hostname that is not this machine must not be reachable through the
  Ollama provider at all - not by configuration, not by default, not by typo.

* **No provider means the feature is absent, not degraded.** There is never a
  silent fall back from a local model to a remote one. That would break the
  offline guarantee in exactly the situation where nobody would notice.

* **The request cannot carry the workbook.** Data minimisation (§29) is a
  property of the type, not of the caller's discipline: `LLMRequest` has fields
  for one expression and the schema of what it references, and there is nowhere
  to put anything else.

`MockProvider` is not a test convenience. It is what CI uses and how the review
flow is built, so it is held to the same contract as the real ones.
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from dashboardbridge_contracts.enums import PrivacyMode
from engines.ai import (
    FieldSchema,
    LLMRequest,
    MockProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    ProviderUnavailable,
)


def answer(coro):
    """Drive one coroutine to completion.

    No pytest-asyncio: it would be a new dependency in a project whose CI
    hand-lists them, for a handful of calls that `asyncio.run` handles exactly
    as well.
    """
    return asyncio.run(coro)


def a_request(**overrides) -> LLMRequest:
    defaults = dict(
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
    return LLMRequest(**{**defaults, **overrides})


# --- the offline guarantee -------------------------------------------------


@pytest.mark.parametrize(
    "host",
    ["api.openai.com", "10.0.0.5", "localhost.evil.example", "0.0.0.0", ""],
)
def test_a_local_provider_refuses_any_host_that_is_not_this_machine(host):
    """The offline guarantee, in code rather than in a comment.

    `localhost.evil.example` is the one that matters: it *starts* with
    "localhost" and resolves wherever its owner likes, so a check written as a
    prefix test would pass it straight through.
    """
    with pytest.raises(ValueError) as caught:
        OllamaProvider(host=host)
    assert "loopback" in str(caught.value).lower()


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_a_local_provider_accepts_the_machine_it_is_running_on(host):
    assert OllamaProvider(host=host).host == host


def test_a_remote_provider_cannot_be_built_in_local_only_mode():
    """`LOCAL_ONLY` is enforced where the call would be made, not only at the API.

    The request contract already refuses this combination. Refusing it again
    here is deliberate: the contract guards one entry point, and this guards
    every caller that ever exists.
    """
    with pytest.raises(ValueError) as caught:
        OpenAICompatibleProvider(
            base_url="https://api.example.com/v1",
            api_key="k",
            privacy_mode=PrivacyMode.LOCAL_ONLY,
        )
    assert "local_only" in str(caught.value).lower()


def test_a_remote_provider_is_allowed_when_the_mode_permits_it():
    provider = OpenAICompatibleProvider(
        base_url="https://api.example.com/v1",
        api_key="k",
        privacy_mode=PrivacyMode.STANDARD,
    )
    assert provider.available() is True


# --- absent, not degraded --------------------------------------------------


def test_a_provider_with_no_credentials_reports_itself_unavailable():
    provider = OpenAICompatibleProvider(
        base_url="https://api.example.com/v1", api_key="", privacy_mode=PrivacyMode.STANDARD
    )
    assert provider.available() is False


def test_generating_from_an_unavailable_provider_raises_rather_than_returning_nothing():
    """A silent `None` here becomes "the model had no suggestion" upstream.

    That is a different claim from "there was no model", and the second one is
    the truth. Only an exception can carry it.
    """
    provider = OpenAICompatibleProvider(
        base_url="https://api.example.com/v1", api_key="", privacy_mode=PrivacyMode.STANDARD
    )
    with pytest.raises(ProviderUnavailable):
        answer(provider.generate(a_request()))


# --- data minimisation is the type's job -----------------------------------


def test_the_request_has_nowhere_to_put_a_workbook():
    """§29, enforced structurally.

    A caller cannot leak the file, the other expressions or a connection string
    through this type, because there is no field for any of them - and the type
    is frozen, so one cannot be attached at runtime either.
    """
    permitted = {field.name for field in dataclasses.fields(LLMRequest)}
    assert permitted == {
        "operation",
        "source_platform",
        "target_platform",
        "expression",
        "fields",
        "rule_ids",
        "refusal_reason",
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        a_request().expression = "something else"


def test_the_field_schema_carries_no_values():
    """The schema of a field, never a row of it."""
    permitted = {field.name for field in dataclasses.fields(FieldSchema)}
    assert permitted == {"table", "name", "datatype"}


# --- the mock is a real provider -------------------------------------------


def test_the_mock_answers_without_a_network_and_says_it_is_a_mock():
    provider = MockProvider()
    assert provider.available() is True

    response = answer(provider.generate(a_request()))
    assert response.text
    assert response.model.startswith("mock")


def test_the_mock_answers_the_same_way_twice():
    """CI runs against it, so a run that differs is a flake nobody can debug."""
    first = answer(MockProvider().generate(a_request()))
    second = answer(MockProvider().generate(a_request()))
    assert first == second


def test_the_mock_can_be_told_to_be_unavailable():
    """The review flow has to be developable against "there is no model" too."""
    provider = MockProvider(available=False)
    assert provider.available() is False
    with pytest.raises(ProviderUnavailable):
        answer(provider.generate(a_request()))
