"""Which migration directions exist, and whether this deployment can run each.

DashboardBridge is one front end over separate engines, sold separately:

| direction | engine | where it lives | licence feature |
|---|---|---|---|
| Tableau -> Power BI | `t2pbi` | this repository | `tableau` |
| Power BI -> Tableau | `t2pbi` | this repository | `tableau` |
| MicroStrategy -> Power BI | `mstr2pbi` | MicroStrategy-to-Power-BI (optional extra) | `microstrategy` |
| Qlik -> Power BI | `qlik2pbi` | Qlik-To-PowerBI (optional extra) | `qlik` |

A direction is **available** when its engine is installed *and* the licence
allows it. The two failures have different remedies - install a package, or buy
the engine - so they are reported separately and never merged into "unsupported".

## Licences without engine features

Licences issued before engines were sold separately carry only `convert` (and
`ai`). Such a licence names no engine, and is read as covering every engine that
is installed: an existing customer keeps what they have. A licence that names at
least one engine feature is taken at its word and enables exactly those.

The registry is the only place that knows this. The API asks it; the web app
reads its answer from `GET /directions`; nothing else hard-codes a direction.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
from dataclasses import dataclass
from typing import Iterable

from dashboardbridge_contracts import DirectionStatus
from dashboardbridge_contracts.enums import DirectionState, Platform

_NAMES = {
    Platform.TABLEAU: "Tableau",
    Platform.POWERBI: "Power BI",
    Platform.MICROSTRATEGY: "MicroStrategy",
    Platform.QLIK: "Qlik",
}


@dataclass(frozen=True)
class Direction:
    source: Platform
    target: Platform
    engine: str  # engine name, also its distribution name
    module: str  # the importable package whose presence means "installed"
    feature: str  # the licence feature that enables it
    extra: str = ""  # the optional extra that installs it ("" = always installed)

    @property
    def label(self) -> str:
        return f"{_NAMES[self.source]} → {_NAMES[self.target]}"


DIRECTIONS: tuple[Direction, ...] = (
    Direction(Platform.TABLEAU, Platform.POWERBI, "t2pbi", "engines.t2pbi", "tableau"),
    Direction(Platform.POWERBI, Platform.TABLEAU, "t2pbi", "engines.t2pbi", "tableau"),
    Direction(Platform.MICROSTRATEGY, Platform.POWERBI, "mstr2pbi", "mstr2pbi", "microstrategy", "microstrategy"),
    Direction(Platform.QLIK, Platform.POWERBI, "qlik2pbi", "qlik2pbi", "qlik", "qlik"),
)

#: Every licence feature that names an engine.
ENGINE_FEATURES = frozenset(d.feature for d in DIRECTIONS)


def find(source: Platform, target: Platform) -> Direction | None:
    return next((d for d in DIRECTIONS if d.source is source and d.target is target), None)


def installed(direction: Direction) -> bool:
    try:
        return importlib.util.find_spec(direction.module) is not None
    except (ImportError, ValueError):
        return False


def _version(direction: Direction) -> str:
    try:
        return importlib.metadata.version(direction.engine)
    except importlib.metadata.PackageNotFoundError:
        return ""


def licensed(direction: Direction, features: Iterable[str] | None) -> bool:
    """See the module docstring: a licence naming no engine covers every installed one."""
    named = set(features or ()) & ENGINE_FEATURES
    return not named or direction.feature in named


def status(direction: Direction, features: Iterable[str] | None) -> DirectionStatus:
    feats = list(features or ())
    if not installed(direction):
        state = DirectionState.NOT_INSTALLED
        extra = f" (the '{direction.extra}' extra: pip install \".[{direction.extra}]\")" if direction.extra else ""
        reason = (f"The {direction.label} engine ({direction.engine}) is not installed on this deployment. "
                  f"Ask your administrator to install it{extra}.")
    elif not licensed(direction, feats):
        state = DirectionState.NOT_LICENSED
        reason = (f"{direction.label} is not included in this licence. "
                  f"Add the '{direction.feature}' engine to the licence to enable it.")
    else:
        state, reason = DirectionState.AVAILABLE, ""
    return DirectionStatus(
        source_platform=direction.source,
        target_platform=direction.target,
        state=state,
        engine=direction.engine,
        engine_version=_version(direction) if state is not DirectionState.NOT_INSTALLED else "",
        licence_feature=direction.feature,
        reason=reason,
    )


def statuses(features: Iterable[str] | None) -> list[DirectionStatus]:
    feats = list(features or ())
    return [status(d, feats) for d in DIRECTIONS]
