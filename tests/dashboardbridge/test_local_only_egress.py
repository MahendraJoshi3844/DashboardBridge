"""No outbound connection during a conversion (`P7.8`, Phase 7's acceptance).

The phase's criterion, in its own words: *"in `LOCAL_ONLY`, a network egress
test proves zero outbound connections during a full conversion."* This is that
test, and it is the only mechanical evidence the product's central promise has —
`CLAUDE.md`'s "offline only: no workbook content may leave the machine, no
network calls in the conversion path."

## Why the positive control is the most important test here

An egress test is the kind that passes for the wrong reason. If the patch is
applied to the wrong name, or a later refactor moves the call it was watching,
the guard records nothing, every assertion of the form "nothing connected"
holds, and the file goes on reporting success while watching an empty room.

So `test_the_guard_catches_a_connection_it_is_meant_to_catch` deliberately makes
a connection through the same harness and asserts it was seen. If that test ever
fails, **every other test in this file is meaningless** regardless of whether it
passes, and its name says so.

## What this can and cannot see

It sees anything that reaches the network through Python's `socket` module,
which is everything the standard library, `httpx`, `requests` and `urllib` do —
a TLS socket is a `socket.socket` too. It also watches name resolution, because
looking up `api.example.com` tells a DNS server something even when no
connection follows; a hostname is data leaving the machine.

It does **not** see a subprocess, a C extension holding its own file
descriptors, or a memory-mapped device. Nothing in the conversion path does any
of those today, and this test would not notice if one started. That is a real
limit, not a hedge: proving the absence of egress from inside the process is
only as good as the assumption that the process is where the egress would be.
"""

from __future__ import annotations

import socket
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PREFIX = "/api/v1"


class Egress(OSError):
    """Raised at the point of the attempt, so a traceback names the caller.

    An `OSError` rather than a new exception type, because that is what an
    unreachable network raises and the code under test should behave the way it
    would on an air-gapped machine. `assist.runtime_available` found this: it
    catches `OSError` and answers "no runtime", and a guard raising anything
    else made it raise instead - testing the product's behaviour under a
    condition that cannot occur rather than under the one being simulated.

    The assertion is always on what was *recorded*, never on what was raised, so
    a caller that swallows the error still cannot hide the attempt.
    """


@contextmanager
def watched(monkeypatch):
    """Record and refuse every outbound connection and name lookup.

    Refusing rather than only recording is deliberate: a call that is allowed to
    succeed may hand back data the rest of the conversion then depends on, and
    the test would be reporting on a run that no longer resembles the real one.
    """
    seen: list[tuple[str, object]] = []

    def refuse(kind):
        def blocked(*args, **kwargs):
            target = args[1] if kind == "socket.connect" else args[0]
            seen.append((kind, target))
            raise Egress(f"{kind} to {target!r}")

        return blocked

    monkeypatch.setattr(socket.socket, "connect", refuse("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", refuse("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", refuse("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", refuse("getaddrinfo"))
    yield seen


# --- the control ---------------------------------------------------------------


def test_the_guard_catches_a_connection_it_is_meant_to_catch(monkeypatch):
    """**If this fails, nothing else in this file means anything.**

    An egress test that watches the wrong name records nothing and passes. This
    is the one test here that proves the harness is looking at the right place,
    so it makes a connection on purpose and insists it was seen.
    """
    with watched(monkeypatch) as seen:
        with pytest.raises(Egress):
            socket.create_connection(("example.invalid", 443), timeout=0.01)
        with pytest.raises(Egress):
            socket.socket().connect(("203.0.113.1", 443))
        with pytest.raises(Egress):
            socket.getaddrinfo("example.invalid", 443)

    assert [kind for kind, _ in seen] == [
        "create_connection",
        "socket.connect",
        "getaddrinfo",
    ]


def test_the_guard_reports_where_the_attempt_was_going(monkeypatch):
    """A guard that says "something connected" is barely better than none: the
    point of a failure here is to name the destination so it can be traced."""
    with watched(monkeypatch) as seen:
        with pytest.raises(Egress):
            socket.create_connection(("api.example.com", 443))

    assert seen[0][1] == ("api.example.com", 443)


def test_the_guard_catches_an_attempt_made_from_inside_the_product(monkeypatch):
    """The control that matters more than the one above.

    Patching a name in the test file proves the test file can see itself. It
    does not prove the patch reaches product code: a module that did `from
    socket import create_connection` at import time would hold the original
    function, and the guard would watch a name nobody calls.

    `t2pbi/assist.py` is the one module in the repository that opens a
    socket - it probes a local model runtime, and it is the named exception in
    `test_ai_boundaries.py`. So it is the honest subject: if the guard sees this
    call, it can see one made from anywhere else in the engine too.
    """
    from t2pbi import assist

    with watched(monkeypatch) as seen:
        # Returns False rather than raising: the probe treats any OSError as
        # "no runtime", which is exactly what an air-gapped machine looks like.
        assert assist.runtime_available(timeout_s=0.01) is False

    assert [kind for kind, _ in seen] == ["create_connection"]


# --- the conversion path --------------------------------------------------------


def test_a_full_conversion_opens_no_connection(monkeypatch):
    """Extract, parse, map, translate, generate, report - end to end, offline.

    Run against `clashes.twb` rather than the smallest fixture available: the
    workbook with cross-table name clashes is the one whose translation does the
    most resolution work, and resolution is where a lookup would be tempting.
    """
    from t2pbi import pipeline

    with watched(monkeypatch) as seen, tempfile.TemporaryDirectory() as out:
        pipeline.run(FIXTURES / "clashes.twb", out)

    assert seen == []


def test_writing_a_tableau_workbook_opens_no_connection(monkeypatch):
    """The other direction (`P6b`), which the acceptance criterion predates."""
    from engines.adapters.powerbi import PowerBIAdapter
    from engines.adapters.tableau_emit import write_twb

    with watched(monkeypatch) as seen, tempfile.TemporaryDirectory() as out:
        write_twb(PowerBIAdapter().read(FIXTURES / "pbip"), out)

    assert seen == []


def test_translating_dax_opens_no_connection(monkeypatch):
    """Both rule packs are files beside the code, and neither is fetched."""
    from t2pbi.core.dax.translator import translate_formula
    from engines.tableau_calc import translate_dax

    with watched(monkeypatch) as seen:
        translate_formula("SUM([Sales])", "Orders")
        translate_dax("SUM(Orders[Sales])", table="Orders")

    assert seen == []


# --- the API path ----------------------------------------------------------------


def test_uploading_analysing_and_converting_over_the_api_opens_no_connection(
    api, monkeypatch
):
    """The whole product surface, not only the engine.

    `LOCAL_ONLY` is the default and is stated explicitly in the request anyway,
    because the promise is about the configured mode rather than about which
    default happened to apply.
    """
    client = api.client
    with watched(monkeypatch) as seen:
        project_id = client.post(
            f"{PREFIX}/projects",
            json={
                "source_platform": "tableau",
                "target_platform": "powerbi",
                "name": "Egress test",
            },
        ).json()["project_id"]
        client.post(
            f"{PREFIX}/projects/{project_id}/artifacts",
            files={
                "file": (
                    "sample.twb",
                    (FIXTURES / "sample.twb").read_bytes(),
                    "application/octet-stream",
                )
            },
        )
        client.post(f"{PREFIX}/projects/{project_id}/analysis")
        started = client.post(
            f"{PREFIX}/projects/{project_id}/conversion",
            json={
                "ai_enabled": False,
                "provider": "none",
                "privacy_mode": "local_only",
            },
        )
        assert started.status_code == 202, started.text
        report = client.get(f"{PREFIX}/projects/{project_id}/report")

    assert report.status_code == 200
    assert seen == []


def test_power_bi_to_tableau_over_the_api_opens_no_connection(api, monkeypatch):
    """`SPEC-powerbi-to-tableau-web.md` AC9: the second direction, end to end.

    Includes the analysis dry run and the validation step, both of which are
    new for this direction and both of which run the writer.
    """
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted((FIXTURES / "pbip").rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(FIXTURES / "pbip").as_posix())

    client = api.client
    with watched(monkeypatch) as seen:
        project_id = client.post(
            f"{PREFIX}/projects",
            json={
                "source_platform": "powerbi",
                "target_platform": "tableau",
                "name": "Egress test",
            },
        ).json()["project_id"]
        client.post(
            f"{PREFIX}/projects/{project_id}/artifacts",
            files={"file": ("Retail.zip", buffer.getvalue(), "application/zip")},
        )
        client.post(f"{PREFIX}/projects/{project_id}/analysis")
        started = client.post(
            f"{PREFIX}/projects/{project_id}/conversion",
            json={"ai_enabled": False, "provider": "none", "privacy_mode": "local_only"},
        )
        assert started.status_code == 202, started.text
        client.post(f"{PREFIX}/projects/{project_id}/validation")
        report = client.get(f"{PREFIX}/projects/{project_id}/report")
        download = client.get(f"{PREFIX}/projects/{project_id}/artifact")

    assert report.status_code == 200
    assert download.status_code == 200
    assert seen == []


# --- the one path that is allowed to reach a socket -------------------------------


def test_asking_a_model_under_local_only_is_refused_before_a_socket_is_opened(
    monkeypatch,
):
    """`LOCAL_ONLY` refuses the provider, and refuses it *early*.

    The distinction is the whole point of the mode. A provider that is
    constructed, connects, and then has its answer discarded has already sent
    the workbook somewhere. `OpenAICompatible` refuses at construction, so the
    refusal happens before any socket exists - and this asserts the absence of
    the socket rather than the presence of the exception.
    """
    from dashboardbridge_contracts.enums import PrivacyMode
    from engines.ai.providers import OpenAICompatibleProvider

    with watched(monkeypatch) as seen:
        with pytest.raises(Exception):
            OpenAICompatibleProvider(
                base_url="https://api.example.com",
                api_key="unused",
                model="unused",
                privacy_mode=PrivacyMode.LOCAL_ONLY,
            )

    assert seen == []


# --- the one hard-coded host -----------------------------------------------------


def test_the_assist_module_refuses_a_host_that_is_not_this_machine(monkeypatch):
    """`assist._HOST` was guarded by a comment, and comments do not run.

    The module's own docstring says "a hostname that is not the local machine
    must never appear here", which is exactly the kind of invariant that erodes
    without anything noticing: a default someone changed, a merge, a typo that
    happens to resolve. `engines/ai/provider.py` already has the check that
    enforces it - `require_loopback`, which reads a literal address with
    `ipaddress` rather than comparing strings, because `localhost.evil.example`
    defeats a prefix test.

    Simulated by moving the constant, which is the only way the invariant can
    actually break: nothing else here is configurable.
    """
    from t2pbi import assist

    monkeypatch.setattr(assist, "_HOST", "api.example.com")

    with watched(monkeypatch) as seen:
        with pytest.raises(ValueError):
            assist.runtime_available(timeout_s=0.01)

    assert seen == [], "it resolved or connected before deciding it was allowed to"


def test_the_assist_module_still_talks_to_loopback(monkeypatch):
    """The check must not cost the feature. `127.0.0.1` is still allowed, and
    the absence of a runtime is still reported as absence rather than error."""
    from t2pbi import assist

    with watched(monkeypatch) as seen:
        assert assist.runtime_available(timeout_s=0.01) is False

    assert [target for _, target in seen] == [("127.0.0.1", 11434)]


def test_sending_a_prompt_is_refused_for_a_host_that_is_not_this_machine(monkeypatch):
    """The probe and the request are two different calls, and only one of them
    carries the workbook's content. Guarding the cheap one would be theatre."""
    from t2pbi import assist

    monkeypatch.setattr(assist, "_HOST", "api.example.com")

    with watched(monkeypatch) as seen:
        with pytest.raises(ValueError):
            assist.suggest_for("Profit Ratio", "SUM([Profit])/SUM([Sales])", "held", "Orders")

    assert seen == []
