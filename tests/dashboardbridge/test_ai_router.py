"""The router (`P4.2`): the only thing that decides a model is reached at all.

07-ai-engine.md gives it one shape and two properties that are easy to erode:

* **No provider means the feature is absent, not degraded.** There is never a
  silent fall back from a local model to a remote one. That would break the
  offline guarantee in the one situation where nobody would notice - the user
  asked for local, got cloud, and the answer looked the same.

* **The router is the only entry point.** Nothing else calls a provider, so
  there is exactly one place where "should this reach a model?" is answered.

Most of these tests are about the paths where a model is *not* reached, because
that is nearly all of them and because each one has to say which of the several
different "no"s it was. "AI is off", "no provider is configured" and "the
provider is configured but nothing is listening" are three different facts and
three different things for a person to do about them.

Nothing here produces something applyable. A draft is raw model output with
`validated=False`; the gauntlet that turns one into a proposal is `P4.4`.
"""

from __future__ import annotations

import asyncio

import pytest

from dashboardbridge_contracts.enums import PrivacyMode, ProviderKind
from engines.ai import FieldSchema, LLMRequest, MockProvider, ProviderUnavailable
from engines.ai.router import AISettings, Disposition, build_provider, route


def answer(coro):
    return asyncio.run(coro)


def a_request() -> LLMRequest:
    return LLMRequest(
        operation="translate_calculation",
        source_platform="tableau",
        target_platform="powerbi",
        expression="{fixed [Order ID]: sum([Profit])} > 0",
        fields=(FieldSchema(table="Orders", name="Profit", datatype="real"),),
        rule_ids=(),
        refusal_reason="Level-of-detail expression.",
    )


class Recording:
    """A provider that records whether it was asked anything."""

    def __init__(self, available: bool = True, text: str = "SUM('Orders'[Profit])"):
        self._available = available
        self._text = text
        self.asked = 0

    def available(self) -> bool:
        return self._available

    async def generate(self, request):
        self.asked += 1
        if not self._available:
            raise ProviderUnavailable("nothing listening")
        from engines.ai import LLMResponse

        return LLMResponse(text=self._text, model="recording-1")


# --- the paths where no model is reached ------------------------------------


def test_ai_switched_off_asks_nothing_and_says_so():
    provider = Recording()
    settings = AISettings(enabled=False, provider=ProviderKind.OLLAMA)

    result = answer(route(a_request(), settings, provider=provider))

    assert result.disposition is Disposition.NOT_ENABLED
    assert result.draft is None
    assert provider.asked == 0, "a disabled router still reached the model"


def test_no_provider_configured_is_its_own_answer():
    """Distinct from "AI is off": the user turned it on and named nothing."""
    settings = AISettings(enabled=True, provider=ProviderKind.NONE)

    result = answer(route(a_request(), settings))

    assert result.disposition is Disposition.NO_PROVIDER
    assert result.draft is None


def test_a_configured_provider_that_is_not_listening_is_not_a_missing_one():
    provider = Recording(available=False)
    settings = AISettings(enabled=True, provider=ProviderKind.OLLAMA)

    result = answer(route(a_request(), settings, provider=provider))

    assert result.disposition is Disposition.PROVIDER_UNAVAILABLE
    assert result.draft is None


def test_the_local_provider_never_falls_back_to_a_remote_one():
    """The property this whole layer exists to keep.

    The settings below carry perfectly usable remote credentials *and* select
    the local provider, which is not listening. The answer is "unavailable" -
    never a quiet cloud call that returns something that looks identical.
    """
    settings = AISettings(
        enabled=True,
        provider=ProviderKind.OLLAMA,
        port=1,  # nothing listens on port 1; refused immediately, on loopback
        base_url="https://api.example.com/v1",
        api_key="a-real-looking-key",
    )

    result = answer(route(a_request(), settings))

    assert result.disposition is Disposition.PROVIDER_UNAVAILABLE
    assert result.draft is None
    assert "example.com" not in result.reason, "the reason names the remote host"


def test_local_only_refuses_a_remote_provider_instead_of_crashing():
    """A contradictory configuration is reported, not raised at the caller."""
    settings = AISettings(
        enabled=True,
        provider=ProviderKind.OPENAI_COMPATIBLE,
        privacy_mode=PrivacyMode.LOCAL_ONLY,
        base_url="https://api.example.com/v1",
        api_key="k",
    )

    result = answer(route(a_request(), settings))

    assert result.disposition is Disposition.REFUSED_BY_PRIVACY
    assert result.draft is None
    assert "local_only" in result.reason.lower()


def test_a_provider_that_dies_mid_call_produces_no_draft():
    class Dies(Recording):
        async def generate(self, request):
            self.asked += 1
            raise ProviderUnavailable("the runtime went away")

    provider = Dies()
    settings = AISettings(enabled=True, provider=ProviderKind.OLLAMA)

    result = answer(route(a_request(), settings, provider=provider))

    assert provider.asked == 1
    assert result.disposition is Disposition.PROVIDER_UNAVAILABLE
    assert result.draft is None


# --- the path where one is ---------------------------------------------------


def test_an_available_provider_produces_a_draft_that_is_not_a_proposal():
    provider = Recording()
    settings = AISettings(enabled=True, provider=ProviderKind.OLLAMA)

    result = answer(route(a_request(), settings, provider=provider))

    assert result.disposition is Disposition.DRAFTED
    assert result.draft is not None
    assert result.draft.text == "SUM('Orders'[Profit])"
    assert result.draft.model == "recording-1"
    assert result.draft.validated is False, (
        "nothing has checked this text; marking it validated here is how "
        "unchecked model output reaches a user"
    )


def test_a_model_that_declines_is_not_recorded_as_a_draft():
    """`UNKNOWN` and an empty answer are both "no", not a draft of nothing."""
    for text in ("UNKNOWN", "", "   "):
        provider = Recording(text=text)
        result = answer(
            route(a_request(), AISettings(enabled=True, provider=ProviderKind.OLLAMA), provider=provider)
        )
        assert result.disposition is Disposition.NO_ANSWER, text
        assert result.draft is None, text


def test_the_same_situation_routes_the_same_way_twice():
    settings = AISettings(enabled=True, provider=ProviderKind.OLLAMA)
    first = answer(route(a_request(), settings, provider=Recording()))
    second = answer(route(a_request(), settings, provider=Recording()))
    assert first == second


# --- building a provider from settings --------------------------------------


def test_the_factory_returns_nothing_when_no_provider_is_named():
    assert build_provider(AISettings(enabled=True, provider=ProviderKind.NONE)) is None


def test_the_factory_passes_the_configured_loopback_host_through():
    provider = build_provider(
        AISettings(enabled=True, provider=ProviderKind.OLLAMA, host="::1", port=9)
    )
    assert provider is not None
    assert provider.host == "::1"
    assert "[::1]:9" in provider.endpoint


def test_the_factory_will_not_build_a_local_provider_on_a_remote_host():
    """The loopback rule is not something a settings object can talk past."""
    with pytest.raises(ValueError):
        build_provider(
            AISettings(enabled=True, provider=ProviderKind.OLLAMA, host="10.0.0.5")
        )


def test_the_mock_provider_is_reachable_through_the_router():
    """CI's path: the whole router exercised with no runtime anywhere."""
    result = answer(
        route(
            a_request(),
            AISettings(enabled=True, provider=ProviderKind.OLLAMA),
            provider=MockProvider(answer="SUM('Orders'[Profit])"),
        )
    )
    assert result.disposition is Disposition.DRAFTED
    assert result.draft is not None
    assert result.draft.model == "mock-1"


# --- the router is what applies the prompt (P4.3) ---------------------------


def test_the_model_receives_the_rendered_prompt_not_the_bare_expression():
    """Without this the safety work in `P4.3` is unreachable.

    A provider handed a raw expression sends a workbook's field to a model with
    no instructions, no fence and nothing saying the text is data - every
    safeguard in the prompt layer bypassed by the one call that matters.
    """
    class Capturing(Recording):
        sent = ""

        async def generate(self, prompt):
            Capturing.sent = prompt
            from engines.ai import LLMResponse

            return LLMResponse(text="SUM('Orders'[Profit])", model="capturing-1")

    request = a_request()
    result = answer(
        route(request, AISettings(enabled=True, provider=ProviderKind.OLLAMA), provider=Capturing())
    )

    assert result.disposition is Disposition.DRAFTED
    assert "# SYSTEM INSTRUCTIONS" in Capturing.sent
    assert "# USER DATA" in Capturing.sent
    assert "<<<USER-DATA " in Capturing.sent
    assert request.expression in Capturing.sent


def test_the_draft_records_which_prompt_version_produced_it():
    """The audit trail has to be able to say what was asked, not only what came back."""
    result = answer(
        route(
            a_request(),
            AISettings(enabled=True, provider=ProviderKind.OLLAMA),
            provider=Recording(),
        )
    )
    assert result.draft is not None
    assert result.draft.prompt_version == 1


def test_an_operation_with_no_prompt_is_refused_before_anything_is_sent():
    """A missing prompt must not degrade into "send the expression on its own"."""
    provider = Recording()
    request = LLMRequest(
        operation="no_such_operation",
        source_platform="tableau",
        target_platform="powerbi",
        expression="SUM([Profit])",
        fields=(),
        rule_ids=(),
        refusal_reason="whatever",
    )

    result = answer(route(request, AISettings(enabled=True, provider=ProviderKind.OLLAMA), provider=provider))

    assert result.disposition is Disposition.NO_PROMPT
    assert result.draft is None
    assert provider.asked == 0, "an expression was sent with no instructions"
