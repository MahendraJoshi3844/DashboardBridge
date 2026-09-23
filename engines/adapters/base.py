"""The platform adapter interface.

One adapter per BI platform. Adapters never know about each other: everything
crosses the canonical model, so N platforms need N adapters rather than N^2
converters.

An adapter may implement read only, write only, or both. That is the honest
model — Tableau is read-only today and Power BI is write-only (ADR-005) — so
`parse`/`normalize` and `generate` are separate capabilities rather than one
interface every adapter must fully satisfy.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from dashboardbridge_contracts import CanonicalModel, Platform


@runtime_checkable
class BIPlatformAdapter(Protocol):
    """What every platform adapter provides."""

    platform: Platform

    def detect(self, data: bytes) -> bool:
        """Is this artifact ours?

        Must be cheap and safe on untrusted input: peek at a header, never parse
        the document. Parsing is expensive and is what needs sandboxing.
        """
        ...


@runtime_checkable
class ReadingAdapter(BIPlatformAdapter, Protocol):
    """An adapter that can read its platform's artifacts."""

    def parse(self, data: bytes) -> Any:
        """Artifact bytes -> the engine's own parse-time representation.

        Returns the engine's IR rather than the canonical model, because parsing
        wants a mutable working structure and the canonical model is frozen
        (ADR-008). `normalize` is the seam.
        """
        ...

    def normalize(self, parsed: Any) -> CanonicalModel:
        """Engine IR -> canonical model. The only thing downstream ever sees."""
        ...


@runtime_checkable
class WritingAdapter(BIPlatformAdapter, Protocol):
    """An adapter that can produce its platform's artifacts."""

    def generate(self, model: CanonicalModel, out_dir: str) -> str:
        """Canonical model -> an artifact on disk. Returns its path."""
        ...
