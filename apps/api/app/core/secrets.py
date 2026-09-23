"""Where a secret comes from (`P7.2`). One seam, one implementation, no pretending.

`config.py` reads `AI_API_KEY` straight from the environment. That works for a
local install and is the wrong shape for anything else: an environment variable
is visible to every child process, appears in a process listing on some systems,
and lands in a container image or a compose file more often than anyone intends.

The roadmap names four backends - env, Key Vault, Secrets Manager, Vault. **Only
`env` is implemented here**, and the other three raise a message saying so. That
is the point rather than a gap: a `KeyVaultSecrets` class that silently fell back
to the environment would let a deployment believe its keys were in a vault while
they sat in `docker-compose.yml`. A configuration naming a backend that does not
exist has to fail at startup, loudly, where somebody can still fix it.

## What a secret is here

Exactly one thing today: the AI provider's API key, and only under `STANDARD`
privacy mode - `LOCAL_ONLY` has no remote provider to hold a key for. Nothing
else in this product has a credential, because there is no database password
(SQLite), no session signing key (no auth yet, `P7.1`), and no outbound service.
That list grows with `P7.1`, and this is the seam it grows through.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


class SecretsUnavailable(RuntimeError):
    """The configured backend cannot be used, and no fallback was attempted.

    Never a fallback: a secret store that quietly degrades to somewhere less
    safe has made its own configuration meaningless.
    """


@runtime_checkable
class SecretProvider(Protocol):
    """Read-only. Nothing in this product writes a secret.

    Deliberately no `set`: a write path is a second place a credential can be
    stored, and the only reason to add one would be an API accepting a
    submitted key - which is exactly what `config.py` says there is nowhere
    safe to do yet.
    """

    name: str

    def get(self, key: str) -> str | None:
        """The secret, or `None` if this backend does not hold it.

        `None` means absent. A backend that cannot be *reached* raises, because
        "the vault is down" and "the key was never set" call for different
        actions and only one of them is the operator's mistake.
        """
        ...


class EnvironmentSecrets:
    """The environment. Honest about what it is, which is not much.

    Good enough for a single-user local install, where the alternative is a
    file on the same disk with the same permissions. Not good enough for a
    shared deployment, which is what the other backends are for.
    """

    name = "env"

    def get(self, key: str) -> str | None:
        value = os.getenv(key)
        return value or None


class UnimplementedSecrets:
    """A named backend that does not exist yet. Raises rather than falling back.

    The failure this prevents: a deployment configured for a vault, running on
    environment variables, believing otherwise. Every one of these is a real
    integration - a client library, credentials of its own, a network path -
    and none of that can be stubbed honestly.
    """

    def __init__(self, name: str, what_it_needs: str) -> None:
        self.name = name
        self._what_it_needs = what_it_needs

    def get(self, key: str) -> str | None:
        raise SecretsUnavailable(
            f"SECRETS_PROVIDER={self.name!r} is not implemented in this build, "
            f"so {key} cannot be read. It needs {self._what_it_needs}. Falling "
            "back to the environment would let this deployment believe its "
            "secrets are in a vault while they are in its process environment, "
            "so it refuses instead. Use SECRETS_PROVIDER=env deliberately, or "
            "implement this backend."
        )


#: The backends the roadmap names, and what each would actually take to build.
#: Listed rather than omitted so that the configuration error names a real
#: thing, and so the size of the remaining work is visible.
_UNIMPLEMENTED = {
    "azure_key_vault": "azure-identity, azure-keyvault-secrets, and a vault URL",
    "aws_secrets_manager": "boto3, a region, and an IAM role or credentials",
    "hashicorp_vault": "hvac, a Vault address, and an auth method",
}


def build_provider(name: str | None = None) -> SecretProvider:
    """The provider named by `SECRETS_PROVIDER`, defaulting to the environment.

    Raises on a name nobody recognises rather than defaulting: a typo in a
    deployment's configuration must not silently select the least safe backend.
    """
    chosen = (name or os.getenv("SECRETS_PROVIDER") or "env").strip().lower()
    if chosen == "env":
        return EnvironmentSecrets()
    if chosen in _UNIMPLEMENTED:
        return UnimplementedSecrets(chosen, _UNIMPLEMENTED[chosen])
    raise SecretsUnavailable(
        f"SECRETS_PROVIDER={chosen!r} is not a backend this knows. Known names: "
        f"env, {', '.join(sorted(_UNIMPLEMENTED))}. Refusing rather than "
        "defaulting to the environment, because a typo must not choose the "
        "least safe option on someone's behalf."
    )
