"""Provider configuration over the API (`P4.7`): what a browser may know.

07-ai-engine.md and the `ProviderSettings` contract: *"Keys are write-only over
the API. A GET never returns the value, nor a masked prefix, which leaks length
and usually the first characters."*

This endpoint goes one step further and is read-only. A credential *write* path
needs somewhere to put the credential, and `P7.2` - the secret provider
abstraction, env / Key Vault / Secrets Manager / Vault - is where that is
designed. Accepting a key over HTTP into a database column in the meantime would
be building `P7.2` badly and then having to unbuild it, with a plaintext secret
in a backup in between. So the key is set where the process reads it, and the
API only ever reports *whether* one is there.

What the browser gets is therefore: which provider, its base URL and model, and
whether it is configured and reachable. Never the secret, in any form.
"""

from __future__ import annotations

import json

PREFIX = "/api/v1"


def test_the_settings_say_which_provider_is_configured(api):
    response = api.client.get(f"{PREFIX}/settings/ai")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "none"
    assert body["configured"] is False


def test_nothing_in_the_response_could_be_a_key(api, monkeypatch):
    """The whole point. Not the value, not a prefix, not a length.

    A masked prefix leaks the length and usually the first characters, which
    for most key formats is most of what an attacker wants.
    """
    secret = "sk-live-0123456789abcdefghijklmnop"
    monkeypatch.setenv("AI_API_KEY", secret)
    monkeypatch.setenv("AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AI_BASE_URL", "https://api.example.com/v1")
    _forget_cached_settings()

    raw = api.client.get(f"{PREFIX}/settings/ai").text
    body = json.loads(raw)

    assert body["configured"] is True, "a key is set, and that fact is reportable"
    assert secret not in raw
    for length in (4, 6, 8):
        assert secret[:length] not in raw, f"a {length}-character prefix leaked"
    assert str(len(secret)) not in raw
    assert not any("key" in name.lower() for name in body), body


def test_a_key_cannot_be_set_through_the_api(api):
    """Deliberate, and locked in so it is not "fixed" by someone in a hurry.

    Until `P7.2` there is nowhere safe to put a submitted credential. A route
    that accepted one would have to store it, and the only place available is a
    database column that ends up in a backup in plaintext.
    """
    for method in (api.client.put, api.client.post, api.client.patch):
        response = method(f"{PREFIX}/settings/ai", json={"api_key": "sk-nope"})
        assert response.status_code in {404, 405}, (
            f"{method.__name__.upper()} accepted a credential over HTTP"
        )


def test_a_remote_provider_under_local_only_is_reported_as_unusable(api, monkeypatch):
    """A contradiction is shown, not resolved in either direction.

    Silently ignoring the provider would look like "AI is off"; silently
    honouring it would send a workbook off the machine. The screen has to be
    able to say which two settings disagree.
    """
    monkeypatch.setenv("AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AI_API_KEY", "sk-live-something")
    monkeypatch.setenv("PRIVACY_MODE", "local_only")
    _forget_cached_settings()

    body = api.client.get(f"{PREFIX}/settings/ai").json()

    assert body["available"] is False
    assert "local_only" in body["unavailable_because"].lower()


def test_a_local_provider_that_is_not_running_is_configured_but_unavailable(
    api, monkeypatch
):
    """Two different facts, and the screen needs both.

    "You have not set this up" and "you set it up and it is not running" lead
    to completely different next steps.
    """
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("PRIVACY_MODE", "local_only")
    monkeypatch.setenv("AI_PORT", "1")  # nothing listens there
    _forget_cached_settings()

    body = api.client.get(f"{PREFIX}/settings/ai").json()

    assert body["provider"] == "ollama"
    assert body["configured"] is True
    assert body["available"] is False
    assert body["unavailable_because"]


def _forget_cached_settings() -> None:
    from app.core.config import settings

    settings.cache_clear()
