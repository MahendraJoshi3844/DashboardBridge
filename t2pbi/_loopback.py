"""The offline guarantee for the local AI assist: talk to this machine only.

A copy of DashboardBridge's `engines.ai.provider.require_loopback`, so the
Tableau engine stands alone. Keep the two in step; both are tested.
"""

from __future__ import annotations

import ipaddress

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
