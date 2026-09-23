"""Where a secret comes from (`P7.2`).

`config.py` read `AI_API_KEY` straight from the environment. That is right for a
local install and wrong for anything shared: an environment variable is visible
to every child process and ends up in a compose file more often than intended.

The roadmap names four backends. **One is implemented.** The other three raise,
and these tests exist to keep them raising, because the failure they prevent is
specific and quiet: a deployment configured for a vault, running on environment
variables, with nothing anywhere saying so.
"""

from __future__ import annotations

import pytest

from app.core.secrets import (
    EnvironmentSecrets,
    SecretProvider,
    SecretsUnavailable,
    build_provider,
)


def test_the_environment_backend_reads_the_environment(monkeypatch):
    monkeypatch.setenv("A_SECRET", "value")
    assert EnvironmentSecrets().get("A_SECRET") == "value"


def test_an_unset_secret_is_absent_rather_than_empty(monkeypatch):
    """`""` and "not set" are the same thing to `os.getenv` and different
    things to a caller deciding whether a provider is configured."""
    monkeypatch.setenv("A_SECRET", "")
    assert EnvironmentSecrets().get("A_SECRET") is None


def test_env_is_the_default(monkeypatch):
    monkeypatch.delenv("SECRETS_PROVIDER", raising=False)
    assert build_provider().name == "env"


@pytest.mark.parametrize(
    "backend", ["azure_key_vault", "aws_secrets_manager", "hashicorp_vault"]
)
def test_a_named_but_unbuilt_backend_refuses_rather_than_falling_back(
    backend, monkeypatch
):
    """The failure this prevents, stated once per backend.

    A class that fell back to the environment would let a deployment believe
    its keys are in a vault while they are in its process environment - and
    nothing would ever say otherwise.
    """
    monkeypatch.setenv("SECRETS_PROVIDER", backend)
    monkeypatch.setenv("AI_API_KEY", "would-have-been-returned")

    provider = build_provider()
    with pytest.raises(SecretsUnavailable) as raised:
        provider.get("AI_API_KEY")

    assert "not implemented" in str(raised.value)
    assert "would-have-been-returned" not in str(raised.value)


def test_the_refusal_names_what_the_backend_would_need():
    """So the remaining work is visible rather than described as "later"."""
    provider = build_provider("hashicorp_vault")
    with pytest.raises(SecretsUnavailable) as raised:
        provider.get("AI_API_KEY")
    assert "hvac" in str(raised.value)


def test_an_unknown_backend_name_raises_rather_than_defaulting(monkeypatch):
    """A typo must not choose the least safe option on someone's behalf."""
    monkeypatch.setenv("SECRETS_PROVIDER", "vualt")
    with pytest.raises(SecretsUnavailable) as raised:
        build_provider()
    assert "vualt" in str(raised.value)


def test_every_backend_satisfies_the_protocol():
    assert isinstance(EnvironmentSecrets(), SecretProvider)
    assert isinstance(build_provider("azure_key_vault"), SecretProvider)


def test_there_is_no_write_path():
    """A write path is a second place a credential can be stored. The only
    reason to add one is an API accepting a submitted key, which `config.py`
    says there is nowhere safe to do yet."""
    assert not hasattr(EnvironmentSecrets(), "set")


def test_the_api_key_still_reaches_settings_through_the_provider(monkeypatch):
    """The seam must not have cost the thing it replaced."""
    from app.core.config import settings

    monkeypatch.setenv("SECRETS_PROVIDER", "env")
    monkeypatch.setenv("AI_API_KEY", "sk-test")
    settings.cache_clear()
    assert settings().ai_api_key == "sk-test"
