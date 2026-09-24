"""What a browser may know about the model configuration (`P4.7`).

Read-only, deliberately. The `ProviderSettings` contract says a GET never
returns a key "nor a masked prefix, which leaks length and usually the first
characters" - and this goes further: there is no write route either.

A credential write path needs somewhere to put the credential, and `P7.2` is
where that is designed (env / Key Vault / Secrets Manager / Vault). Accepting a
key over HTTP into a database column in the meantime would be building `P7.2`
badly and then having to unbuild it, with a plaintext secret sitting in a backup
in between. So the key is set where the process reads it, and this reports only
whether one is there.

The response separates *configured* from *available* because they are different
facts with different remedies: "you have not set this up" and "you set it up and
it is not running" send a person to completely different places.
"""

from __future__ import annotations

from dashboardbridge_contracts import ProviderSettings
from dashboardbridge_contracts.enums import PrivacyMode, ProviderKind
from fastapi import APIRouter

from app.core.config import settings
from engines.ai.router import AISettings, build_provider

router = APIRouter(tags=["settings"])


def _ai_settings() -> AISettings:
    current = settings()
    return AISettings(
        enabled=current.ai_provider is not ProviderKind.NONE,
        provider=current.ai_provider,
        privacy_mode=current.privacy_mode,
        base_url=current.ai_base_url,
        api_key=current.ai_api_key,
        host=current.ai_host,
        model=current.ai_model,
        # Only when configured; otherwise the provider's own default stands.
        **({"port": current.ai_port} if current.ai_port else {}),
        **({"timeout_s": current.ai_timeout_s} if current.ai_timeout_s else {}),
    )


@router.get("/settings/ai", response_model=ProviderSettings)
def get_ai_settings() -> ProviderSettings:
    current = settings()
    configured = _is_configured(current)

    if current.ai_provider is ProviderKind.NONE:
        return ProviderSettings(
            provider=ProviderKind.NONE,
            available=False,
            unavailable_because=(
                "No provider is configured, so every AI path is absent rather "
                "than degraded."
            ),
        )

    common = {
        "provider": current.ai_provider,
        "base_url": current.ai_base_url,
        "model": current.ai_model,
        "configured": configured,
    }

    try:
        provider = build_provider(_ai_settings())
    except ValueError as exc:
        # A contradiction - a remote provider under LOCAL_ONLY, say. Reported
        # rather than resolved in either direction: ignoring it would read as
        # "AI is off", honouring it would send a workbook off the machine.
        return ProviderSettings(**common, available=False, unavailable_because=str(exc))

    if provider is None or not configured:
        return ProviderSettings(
            **common,
            available=False,
            unavailable_because=(
                "The provider is named but has no credential, so nothing can "
                "be sent to it."
            ),
        )

    if not provider.available():
        return ProviderSettings(
            **common,
            available=False,
            unavailable_because=(
                "The provider is configured but is not answering. Nothing is "
                "sent anywhere else when it does not."
            ),
        )

    return ProviderSettings(**common, available=True)


def _is_configured(current) -> bool:
    """A local runtime needs no credential; a remote one is nothing without."""
    if current.ai_provider is ProviderKind.OLLAMA:
        return True
    if current.ai_provider is ProviderKind.OPENAI_COMPATIBLE:
        return bool(current.ai_api_key)
    return False


__all__ = ["router", "PrivacyMode"]
