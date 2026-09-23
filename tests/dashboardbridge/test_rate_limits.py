"""Rate limits (`P7.6`).

What this protects is not a login form — there isn't one yet (`P7.1`). It is the
**cost** of the expensive endpoints: an upload writes to disk, an analysis and a
conversion each parse a workbook and run the whole pipeline. A client in a loop
against those is a denial of service against the machine, whether or not anyone
meant it that way.

So the limit is by *cost*, not uniformly: reads are cheap and generously
allowed, writes are the ones that do work. Both are configurable, and setting
either to zero turns that class off, because a limit nobody can lift is one that
eventually stops legitimate work with no way out.

## What this cannot do, stated

The counter lives **in this process**. Two workers have two counters and a
client gets twice the limit; a restart forgets everything. That is honest for
the deployment this has today - one process, one machine - and it is the first
thing to replace with shared state if this is ever run behind more than one
worker. A limiter that quietly allows N times the limit is worse than none,
because the number in the configuration stops being true.

Identity is the client address, which is the only identity there is before
`P7.1`. Behind a proxy every client shares one, and `X-Forwarded-For` is not
consulted: trusting a header a client sets would let anyone opt out of the
limit by inventing an address.
"""

from __future__ import annotations

import pytest

from app.core.rate_limit import RateLimiter

PREFIX = "/api/v1"


class FakeClock:
    """Time under the test's control. A limiter tested with real sleeps is a
    slow suite that still cannot say what happens at the window boundary."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# --- the limiter itself ----------------------------------------------------------


def test_requests_within_the_limit_are_allowed():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=3, clock=clock)
    assert [limiter.check("a").allowed for _ in range(3)] == [True, True, True]


def test_the_request_past_the_limit_is_refused():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=3, clock=clock)
    for _ in range(3):
        limiter.check("a")
    assert limiter.check("a").allowed is False


def test_a_refusal_says_how_long_to_wait():
    """A 429 with no `Retry-After` tells a client to guess, and clients guess
    by retrying immediately."""
    clock = FakeClock()
    limiter = RateLimiter(per_minute=2, clock=clock)
    limiter.check("a")
    limiter.check("a")
    clock.advance(20)

    verdict = limiter.check("a")
    assert verdict.allowed is False
    assert 0 < verdict.retry_after_seconds <= 60


def test_the_window_moves_rather_than_resetting_on_the_minute():
    """A fixed window lets a client send double the limit across a boundary -
    all of it at 59 seconds, all of it again at 61. The limit is per minute,
    so the minute has to be the last one and not the one on the clock.

    The calls have to be **spread across the boundary** to tell the two apart.
    An earlier version of this test made both calls at the same instant, and a
    deliberately-broken fixed-window implementation passed it: with identical
    timestamps every window behaves the same. Found by breaking the code and
    watching nothing fail.
    """
    clock = FakeClock()
    clock.now = 1020.0  # exactly on a minute, so "the minute on the clock" is
    limiter = RateLimiter(per_minute=2, clock=clock)  # unambiguous

    clock.advance(59)  # late in that minute
    assert limiter.check("a").allowed
    assert limiter.check("a").allowed  # the allowance is now spent

    clock.advance(2)
    # Two seconds later, and a new minute by the clock. A fixed window would
    # hand over a fresh allowance here - four calls in two seconds against a
    # limit of two per minute. Both calls are two seconds old, so the last
    # sixty seconds still hold two of them.
    assert limiter.check("a").allowed is False

    clock.advance(59)
    # Now they really are more than a minute old.
    assert limiter.check("a").allowed is True


def test_two_clients_are_counted_separately():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=1, clock=clock)
    assert limiter.check("a").allowed is True
    assert limiter.check("b").allowed is True
    assert limiter.check("a").allowed is False


def test_a_limit_of_zero_turns_the_limiter_off():
    """A limit nobody can lift eventually stops legitimate work with no way
    out, so there has to be a way to say "not here"."""
    limiter = RateLimiter(per_minute=0, clock=FakeClock())
    assert all(limiter.check("a").allowed for _ in range(1000))


def test_old_entries_do_not_accumulate_forever():
    """The limiter is a dictionary that every distinct client adds to. Without
    eviction it is a memory leak with a network-facing key."""
    clock = FakeClock()
    limiter = RateLimiter(per_minute=1, clock=clock)
    for index in range(500):
        limiter.check(f"client-{index}")
    clock.advance(120)
    limiter.check("someone")
    assert limiter.tracked_clients() < 500


# --- over the API -----------------------------------------------------------------


def test_a_client_past_the_write_limit_gets_429_with_the_projects_error_shape(api):
    """Two messages, always (§46): one for a person, one for an engineer."""
    from app.main import app

    app.state.rate_limiter.configure(per_minute_write=2, per_minute_read=0)

    client = api.client
    body = {
        "source_platform": "tableau",
        "target_platform": "powerbi",
        "name": "Rate limit test",
    }
    statuses = [client.post(f"{PREFIX}/projects", json=body).status_code for _ in range(4)]

    assert 429 in statuses
    refused = client.post(f"{PREFIX}/projects", json=body)
    assert refused.status_code == 429
    assert refused.headers.get("retry-after")
    payload = refused.json()
    assert payload["message"] and payload["detail"]
    assert payload["request_id"]


def test_reads_are_not_refused_by_the_write_limit(api):
    """The limit is by cost. Refusing a health check because someone uploaded
    too much makes the service look down when it is working."""
    from app.main import app

    app.state.rate_limiter.configure(per_minute_write=1, per_minute_read=0)

    client = api.client
    client.post(
        f"{PREFIX}/projects",
        json={
            "source_platform": "tableau",
            "target_platform": "powerbi",
            "name": "One",
        },
    )
    assert all(client.get(f"{PREFIX}/health").status_code == 200 for _ in range(20))


def test_the_limiter_is_off_by_default_in_the_test_suite(api):
    """Stated so nobody debugs a 429 that a neighbouring test caused.

    The limiter is process-global and the suite fires hundreds of requests, so
    the fixture resets it. A test that wants a limit sets one, as above.
    """
    client = api.client
    statuses = {
        client.post(
            f"{PREFIX}/projects",
            json={
                "source_platform": "tableau",
                "target_platform": "powerbi",
                "name": f"P{index}",
            },
        ).status_code
        for index in range(30)
    }
    assert 429 not in statuses


def test_a_forwarded_for_header_cannot_buy_a_fresh_allowance(api):
    """Otherwise the limit is opt-in, and anyone can opt out by inventing an
    address. Behind a real proxy this must be configured deliberately, not
    inferred from a header the client controls."""
    from app.main import app

    app.state.rate_limiter.configure(per_minute_write=2, per_minute_read=0)

    client = api.client
    body = {
        "source_platform": "tableau",
        "target_platform": "powerbi",
        "name": "Spoof",
    }
    for _ in range(3):
        client.post(f"{PREFIX}/projects", json=body)

    spoofed = client.post(
        f"{PREFIX}/projects", json=body, headers={"X-Forwarded-For": "10.1.2.3"}
    )
    assert spoofed.status_code == 429
