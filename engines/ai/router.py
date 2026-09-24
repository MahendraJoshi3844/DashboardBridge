"""The one place that decides whether a model is reached (`P4.2`).

07-ai-engine.md:

    conversion task
       ↓
    can a deterministic rule finish it?  ── yes ──▶ rule engine, done
       ↓ no
    is AI enabled and a provider available?  ── no ──▶ flag ai_required
       ↓ yes
    minimise payload → prompt → provider → schema → rules → security → proposal

The router is entered only after the deterministic path has refused. It does not
decide *whether* an expression could have been converted by rule - by the time
it is called, that question has been answered and the answer was no.

## Why every "no" is a different value

`Disposition` has five ways of not producing a draft, and collapsing them into a
boolean would be the easy mistake. "AI is switched off", "AI is on and no
provider is named", "a provider is named and nothing is listening", "this
configuration is forbidden by the privacy mode" and "the model was asked and
declined" are five different facts about the machine, and each one is a
different thing for a person to do next. A screen that renders them all as "no
suggestion available" is a screen that cannot help.

A sixth, `no_prompt`, is not about the machine at all: it means this build is
missing the prompt for the operation, which is a defect here rather than
something a user can act on. It exists so that an absent file can never degrade
into sending an expression with no instructions attached.

## No fallback, ever

If the configured provider cannot answer, that is the answer. There is no second
attempt against a different provider, and in particular no attempt against a
remote one - a local provider is chosen so that workbook content stays on the
machine, and quietly satisfying the request from the cloud would break exactly
the promise the choice was making, invisibly, because the reply looks the same.

## Nothing here is applyable

A `Draft` is raw model text with `validated=False`. Turning one into a proposal
runs the schema, rule and security gauntlet (`P4.4`), and applying one is a
person's decision (ADR-007). Until that exists a draft has no consumer, which is
deliberate: unchecked model output has nowhere to go.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from dashboardbridge_contracts.enums import PrivacyMode, ProviderKind

from engines.ai.prompts import PromptNotFound, load_prompt, render, render_advice
from engines.ai.provider import LLMProvider
from engines.ai.providers import OllamaProvider, OpenAICompatibleProvider
from engines.ai.types import LLMRequest, ProviderUnavailable

#: What a model says when it has nothing useful. Treated as "no", never as a
#: draft whose text happens to be a refusal word.
_DECLINED = {"unknown", ""}


class Disposition(str, Enum):
    """What became of the routing attempt."""

    NOT_ENABLED = "not_enabled"
    NO_PROVIDER = "no_provider"
    NO_PROMPT = "no_prompt"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    REFUSED_BY_PRIVACY = "refused_by_privacy"
    NO_ANSWER = "no_answer"
    DRAFTED = "drafted"


@dataclass(frozen=True)
class AISettings:
    """How this machine is configured to reach a model, if at all."""

    enabled: bool = False
    provider: ProviderKind = ProviderKind.NONE
    privacy_mode: PrivacyMode = PrivacyMode.STANDARD
    #: Remote provider.
    base_url: str = ""
    api_key: str = ""
    #: Local provider. `host` is validated as loopback when the provider is built.
    host: str = "127.0.0.1"
    port: int = 11434
    model: str = ""
    #: Seconds to wait for an answer. A local 8B model on a CPU takes tens of
    #: seconds for a paragraph; None keeps the provider's own default.
    timeout_s: float | None = None


@dataclass(frozen=True)
class Draft:
    """Raw model output. Not a proposal - nothing has checked it yet."""

    text: str
    model: str
    #: Which kind of provider produced it, for the audit trail.
    provider: str
    #: Which prompt asked for it. The trail has to be able to say what was
    #: asked, not only what came back.
    prompt_version: int = 0
    #: Always False until the `P4.4` gauntlet exists to set it.
    validated: bool = False


@dataclass(frozen=True)
class Routed:
    """The outcome, and the sentence explaining it."""

    disposition: Disposition
    reason: str
    draft: Draft | None = None


def build_provider(settings: AISettings) -> LLMProvider | None:
    """Construct the configured provider, or nothing.

    Raises rather than returning `None` when the configuration is impossible -
    a remote host on a local provider, say. A silent `None` there would read as
    "no provider is configured", which is the one thing it is not: a provider
    *was* configured, wrongly, and someone needs to know.
    """
    if settings.provider is ProviderKind.NONE:
        return None
    if settings.provider is ProviderKind.OLLAMA:
        return OllamaProvider(
            host=settings.host,
            port=settings.port,
            **({"model": settings.model} if settings.model else {}),
            **({"timeout_s": settings.timeout_s} if settings.timeout_s else {}),
        )
    return OpenAICompatibleProvider(
        base_url=settings.base_url,
        api_key=settings.api_key,
        privacy_mode=settings.privacy_mode,
        **({"model": settings.model} if settings.model else {}),
    )


async def route(
    request: LLMRequest,
    settings: AISettings,
    provider: LLMProvider | None = None,
) -> Routed:
    """Decide whether to ask a model, and ask it if so.

    `provider` is injectable so the review flow and CI can run the whole router
    against `MockProvider` with no runtime anywhere. It does not widen what is
    reachable: each provider enforces its own rules at construction, so an
    injected one has already passed them.
    """
    if not settings.enabled:
        return Routed(
            Disposition.NOT_ENABLED,
            "AI assistance is switched off, so nothing was sent to a model.",
        )

    if provider is None:
        try:
            provider = build_provider(settings)
        except ValueError as exc:
            # A configuration the provider layer forbids - a remote host on a
            # local provider, or a remote provider under LOCAL_ONLY.
            return Routed(Disposition.REFUSED_BY_PRIVACY, str(exc))

    if provider is None:
        return Routed(
            Disposition.NO_PROVIDER,
            "AI assistance is on, but no provider is configured, so there was "
            "nothing to ask.",
        )

    # Before anything is sent. A missing prompt must not degrade into "send the
    # expression on its own", which is every safeguard in the prompt layer
    # bypassed at once by an absent file.
    try:
        prompt = load_prompt(request.operation)
    except PromptNotFound as exc:
        return Routed(Disposition.NO_PROMPT, str(exc))

    kind = type(provider).__name__
    if not provider.available():
        # The end of the line. Trying a different provider here is what would
        # turn a local-only choice into a cloud call nobody asked for.
        return Routed(
            Disposition.PROVIDER_UNAVAILABLE,
            f"The configured provider ({kind}) is not answering. Nothing was "
            "sent anywhere else.",
        )

    try:
        # A proposal is checked as JSON, so a provider that can be held to
        # JSON is. llama3.1 wraps an otherwise correct answer in a code fence
        # when it is merely asked, and reading one out of a fence is the
        # guessing `vet` refuses to do.
        if getattr(provider, "supports_json_mode", False):
            response = await provider.generate(render(prompt, request), json_mode=True)
        else:
            response = await provider.generate(render(prompt, request))
    except ProviderUnavailable as exc:
        return Routed(
            Disposition.PROVIDER_UNAVAILABLE,
            f"The configured provider ({kind}) stopped answering: {exc}",
        )

    text = (response.text or "").strip()
    if text.lower() in _DECLINED:
        return Routed(
            Disposition.NO_ANSWER,
            "The model was asked and had no suggestion for this expression.",
        )

    return Routed(
        Disposition.DRAFTED,
        "A model drafted a suggestion. It has not been checked and cannot be "
        "applied until it is.",
        draft=Draft(
            text=text,
            model=response.model,
            provider=kind,
            prompt_version=prompt.version,
        ),
    )


@dataclass(frozen=True)
class AdviceRequest:
    """A question whose answer is prose for a person, never something applied.

    `context` describes the model being worked on - table, column and measure
    names, counts, findings. Every name in it came out of a file we did not
    write, so it is fenced as USER DATA with the person's own `question`; the
    prompt's authored regions are the only trusted text sent.
    """

    operation: str
    context: str
    question: str = ""


async def advise(
    request: AdviceRequest,
    settings: AISettings,
    provider: LLMProvider | None = None,
) -> Routed:
    """Ask a model for advice. The same gates as `route`, in the same order.

    Nothing an answer says is applied. It is shown, labelled as a model's, and
    any change it suggests is still made by a person in the editor (ADR-007).
    """
    if not settings.enabled:
        return Routed(
            Disposition.NOT_ENABLED,
            "AI assistance is switched off, so nothing was sent to a model.",
        )
    if provider is None:
        try:
            provider = build_provider(settings)
        except ValueError as exc:
            return Routed(Disposition.REFUSED_BY_PRIVACY, str(exc))
    if provider is None:
        return Routed(
            Disposition.NO_PROVIDER,
            "AI assistance is on, but no provider is configured, so there was "
            "nothing to ask.",
        )
    try:
        prompt = load_prompt(request.operation)
    except PromptNotFound as exc:
        return Routed(Disposition.NO_PROMPT, str(exc))

    kind = type(provider).__name__
    if not provider.available():
        return Routed(
            Disposition.PROVIDER_UNAVAILABLE,
            f"The configured provider ({kind}) is not answering. Nothing was "
            "sent anywhere else.",
        )
    try:
        response = await provider.generate(
            render_advice(prompt, request.context, request.question)
        )
    except ProviderUnavailable as exc:
        return Routed(
            Disposition.PROVIDER_UNAVAILABLE,
            f"The configured provider ({kind}) stopped answering: {exc}",
        )
    text = (response.text or "").strip()
    if text.lower() in _DECLINED:
        return Routed(Disposition.NO_ANSWER, "The model was asked and had nothing to say.")
    return Routed(
        Disposition.DRAFTED,
        "Advice from a model. Nothing it says has been applied.",
        draft=Draft(text=text, model=response.model, provider=kind, prompt_version=prompt.version),
    )
