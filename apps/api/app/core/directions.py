"""The API's side of the direction registry: refuse what this deployment cannot run.

`engines.conversion.directions` decides; this module turns its answer into the
refusal a route raises. Called where a direction is committed to (creating a
project) and where it is used (analysis, conversion) - the second because an
engine can be uninstalled, or a licence replaced, after a project began.
"""

from __future__ import annotations

from dashboardbridge_contracts import DirectionStatus
from dashboardbridge_contracts.enums import DirectionState, ErrorCategory, Platform

from app.core.errors import ApiException
from app.core.licensing import status as license_status
from engines.conversion import directions as registry


def licence_features() -> list[str] | None:
    licence = license_status().license
    return list(licence.features) if licence is not None else None


def grants_of(user) -> set[str] | None:
    """What limits this person: nothing for an administrator, else their products."""
    if user is None or getattr(user, "is_admin", False):
        return None
    return set(user.products)


def require_direction(source: Platform, target: Platform, user=None) -> DirectionStatus:
    direction = registry.find(source, target)
    if direction is None:
        raise ApiException(
            ErrorCategory.UNSUPPORTED_ARTIFACT,
            f"Converting from {source.value} to {target.value} is not supported.",
            detail=f"no engine is registered for {source.value} -> {target.value}",
            status_code=400,
        )
    result = registry.status(direction, licence_features(), grants_of(user))
    if result.state is DirectionState.NOT_INSTALLED:
        raise ApiException(
            ErrorCategory.UNSUPPORTED_ARTIFACT,
            result.reason,
            detail=f"engine {direction.engine!r} (module {direction.module!r}) is not importable",
            status_code=400,
        )
    if result.state is DirectionState.NOT_LICENSED:
        # 402 for the same reason the conversion gate uses it: the request is
        # allowed, the subscription does not cover it.
        raise ApiException(
            ErrorCategory.VALIDATION_ERROR,
            result.reason,
            detail=f"licence lacks feature {direction.feature!r}",
            status_code=402,
        )
    if result.state is DirectionState.NOT_GRANTED:
        raise ApiException(
            ErrorCategory.AUTH_ERROR,
            result.reason,
            detail=f"user lacks product {direction.feature!r}",
            status_code=403,
        )
    return result
