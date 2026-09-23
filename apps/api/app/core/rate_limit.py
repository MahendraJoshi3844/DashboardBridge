"""Rate limiting (`P7.6`). By cost, in this process, keyed by address.

What this protects is not a login form - there is not one yet (`P7.1`). It is
the **cost** of the expensive endpoints: an upload writes to disk, and an
analysis or a conversion parses a workbook and runs the whole pipeline. A client
looping against those is a denial of service against the machine whether or not
anyone meant it that way.

So reads and writes are counted separately and configured separately. Zero on
either turns that class off, because a limit nobody can lift eventually stops
legitimate work with no way out.

## What this cannot do

**The counter lives in this process.** Two workers have two counters and a
client gets twice the limit; a restart forgets everything. That is honest for
the deployment this has today - one process, one machine - and it is the first
thing to replace with shared state before running behind more than one worker,
because a limiter that quietly allows N times its configured number has made
that number untrue.

**Identity is the client address**, the only identity there is before `P7.1`.
Behind a proxy every client shares one. `X-Forwarded-For` is deliberately not
consulted: trusting a header the client sets makes the limit opt-in.

## Why a sliding window

A fixed window lets a client send double the limit across a boundary - all of it
at 59 seconds and all of it again at 61. The limit says "per minute", so the
minute has to be the last sixty seconds rather than the one on the clock. The
cost is keeping the timestamps, which is bounded by the limit itself.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque

WINDOW_SECONDS = 60.0

#: Generous on purpose. This is a ceiling on runaway cost, not a quota: a person
#: working normally must never meet it, or they will learn to expect failures.
DEFAULT_WRITE_PER_MINUTE = 60
DEFAULT_READ_PER_MINUTE = 600

#: How often the tracking table is swept. Every distinct address adds an entry,
#: so without eviction this is a memory leak with a network-facing key.
_SWEEP_EVERY_SECONDS = 60.0


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    retry_after_seconds: int = 0


class RateLimiter:
    """A sliding-window counter per client. Not thread-safe by design.

    FastAPI serves this app from one event loop, so the middleware calling it
    runs on one thread and a lock would be contention for a race that cannot
    happen. If this is ever driven from a thread pool, that assumption is the
    thing to revisit.
    """

    def __init__(
        self,
        per_minute: int = DEFAULT_WRITE_PER_MINUTE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._per_minute = per_minute
        self._clock = clock
        self._seen: dict[str, Deque[float]] = {}
        self._last_sweep = clock()

    def configure(self, per_minute: int) -> None:
        self._per_minute = per_minute
        self._seen.clear()

    def check(self, client: str) -> Verdict:
        if self._per_minute <= 0:
            return Verdict(allowed=True)

        now = self._clock()
        self._sweep(now)
        window = self._seen.setdefault(client, deque())
        cutoff = now - WINDOW_SECONDS
        while window and window[0] <= cutoff:
            window.popleft()

        if len(window) >= self._per_minute:
            # When the oldest call in the window ages out, one slot frees.
            wait = window[0] + WINDOW_SECONDS - now
            return Verdict(allowed=False, retry_after_seconds=max(1, int(wait) + 1))

        window.append(now)
        return Verdict(allowed=True)

    def tracked_clients(self) -> int:
        return len(self._seen)

    def _sweep(self, now: float) -> None:
        """Drop clients whose whole window has aged out."""
        if now - self._last_sweep < _SWEEP_EVERY_SECONDS:
            return
        self._last_sweep = now
        cutoff = now - WINDOW_SECONDS
        for client in [
            name
            for name, window in self._seen.items()
            if not window or window[-1] <= cutoff
        ]:
            del self._seen[client]


class CostBasedLimiter:
    """Two limiters, because a read and a conversion are not the same request.

    Refusing a health check because someone uploaded too much makes a working
    service look down.
    """

    def __init__(
        self,
        per_minute_write: int = DEFAULT_WRITE_PER_MINUTE,
        per_minute_read: int = DEFAULT_READ_PER_MINUTE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.write = RateLimiter(per_minute_write, clock)
        self.read = RateLimiter(per_minute_read, clock)

    def configure(self, per_minute_write: int, per_minute_read: int) -> None:
        self.write.configure(per_minute_write)
        self.read.configure(per_minute_read)

    def check(self, method: str, client: str) -> Verdict:
        limiter = self.write if method.upper() not in _READ_METHODS else self.read
        return limiter.check(client)


_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
