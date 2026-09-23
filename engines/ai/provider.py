"""The provider protocol, and the loopback rule every local provider obeys.

`P4.1`, 07-ai-engine.md: "Conversion code never imports a vendor." Everything
above this layer speaks `LLMProvider`; adding Azure OpenAI or Anthropic later is
a new class here and no change anywhere else (§26).
"""

from __future__ import annotations

import ipaddress
from typing import Protocol, runtime_checkable

from engines.ai.types import LLMResponse

#: Names that mean "this machine" and cannot be made to mean anything else.
#: Checked as an exact set, never as a prefix: `localhost.evil.example` starts
#: with "localhost" and resolves wherever its owner points it.
_LOOPBACK_NAMES = frozenset({"localhost"})


def require_loopback(host: str) -> str:
    """Refuse any host that is not this machine.

    This function is the offline guarantee in code. A local provider exists so
    that workbook content never leaves the machine, and a configurable host is
    exactly how that promise gets broken - by a default someone changed, an
    environment variable, or a typo that happens to resolve.

    Literal addresses go through `ipaddress`, so the whole 127.0.0.0/8 block and
    IPv6 `::1` are accepted on their own terms rather than by string comparison,
    and something like `0.0.0.0` - which is not a destination at all - is not
    mistaken for one.
    """
    candidate = (host or "").strip().strip("[]")
    if candidate.lower() in _LOOPBACK_NAMES:
        return host
    try:
        if ipaddress.ip_address(candidate).is_loopback:
            return host
    except ValueError:
        pass
    raise ValueError(
        f"{host!r} is not a loopback address. A local provider may only talk to "
        "this machine: that is what keeps workbook content on it. Use "
        "127.0.0.1, ::1 or localhost, or configure a remote provider "
        "explicitly, where the choice is visible."
    )


@runtime_checkable
class LLMProvider(Protocol):
    """What every model runtime looks like from the outside."""

    def available(self) -> bool:
        """Is this provider usable right now?

        Never raises and never blocks for long: callers use it to decide whether
        the feature exists at all, and a feature that hangs while deciding is
        worse than one that is absent.
        """
        ...

    async def generate(self, prompt: str) -> LLMResponse:
        """Send already-rendered text. Raises `ProviderUnavailable` if there is
        no model.

        A provider takes text, not an `LLMRequest`, so that it has no way to
        assemble its own prompt: rendering happens once, in the router, where
        the region boundaries and the fence are applied. A provider that could
        build a prompt could build one without them.
        """
        ...
