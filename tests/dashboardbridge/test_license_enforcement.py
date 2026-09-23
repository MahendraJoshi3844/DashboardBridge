"""What an expired licence stops, and what it deliberately does not (`P7.1`).

The product runs in the customer's environment, so the licence is a signed file
checked offline. This is the half that matters commercially: what the
application actually does when the paid period ends.

**Converting is what a licence buys, so conversion stops.** That is the lever,
and it is the whole lever.

**Reading does not stop.** Past projects, their reports and their flags stay
available. Holding work someone already paid for hostage does not sell a
renewal; it sells resentment, and it would make the product feel hostile at
exactly the moment a customer is deciding whether to keep paying for it. No new
work is the pressure. Losing old work is a threat.

**A missing licence and an expired one are different conversations.** A fresh
deployment needs to know where to put a file. An expiring customer needs a
date and a person to call. Collapsing them into "unlicensed" sends both to the
wrong place.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from engines.licensing import generate_keypair, issue

PREFIX = "/api/v1"


@pytest.fixture(scope="module")
def keys():
    return generate_keypair()


def _install(monkeypatch, keys, *, days: int, issued_days_ago: int = 30) -> None:
    """Put a licence in front of the deployment, expiring in `days`."""
    from app.core import licensing

    private, public = keys
    today = date.today()
    token = issue(
        private_key=private,
        customer="Northwind Analytics",
        issued=today - timedelta(days=issued_days_ago),
        expires=today + timedelta(days=days),
        features=("convert",),
        seats=10,
    )
    monkeypatch.setattr(licensing, "VENDOR_PUBLIC_KEY", public)
    monkeypatch.setenv("LICENSE_KEY", token)
    licensing.status.cache_clear()


def _unlicensed(monkeypatch) -> None:
    from app.core import licensing

    monkeypatch.setattr(licensing, "VENDOR_PUBLIC_KEY", "")
    monkeypatch.delenv("LICENSE_KEY", raising=False)
    monkeypatch.delenv("LICENSE_FILE", raising=False)
    licensing.status.cache_clear()


@pytest.fixture(autouse=True)
def _reset_license_cache():
    """The status is cached for the process, so it must not leak between tests."""
    from app.core import licensing

    licensing.status.cache_clear()
    yield
    licensing.status.cache_clear()


def _ready(client) -> str:
    project_id = client.post(
        f"{PREFIX}/projects",
        json={
            "source_platform": "tableau",
            "target_platform": "powerbi",
            "name": "Licence test",
        },
    ).json()["project_id"]
    from pathlib import Path

    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={
            "file": (
                "sample.twb",
                (fixtures / "sample.twb").read_bytes(),
                "application/octet-stream",
            )
        },
    )
    client.post(f"{PREFIX}/projects/{project_id}/analysis")
    return project_id


def _convert(client, project_id: str):
    return client.post(
        f"{PREFIX}/projects/{project_id}/conversion",
        json={"ai_enabled": False, "provider": "none", "privacy_mode": "local_only"},
    )


# --- while the licence is good -------------------------------------------------------


def test_a_valid_licence_converts(api, monkeypatch, keys):
    _install(monkeypatch, keys, days=200)
    client = api.client
    assert _convert(client, _ready(client)).status_code == 202


def test_a_licence_near_expiry_still_converts_and_says_so(api, monkeypatch, keys):
    """The warning has to arrive while there is still time to act on it."""
    _install(monkeypatch, keys, days=9)
    client = api.client
    assert _convert(client, _ready(client)).status_code == 202

    body = client.get(f"{PREFIX}/license").json()
    assert body["expiring_soon"] is True
    assert "9 days" in (body["message"] or "")


# --- once it has expired --------------------------------------------------------------


def test_an_expired_licence_refuses_to_convert(api, monkeypatch, keys):
    _install(monkeypatch, keys, days=-1, issued_days_ago=400)
    client = api.client
    response = _convert(client, _ready(client))
    assert response.status_code == 402, response.text


def test_the_refusal_names_the_date_and_says_to_renew(api, monkeypatch, keys):
    _install(monkeypatch, keys, days=-1, issued_days_ago=400)
    client = api.client
    body = _convert(client, _ready(client)).json()
    assert "renew" in body["message"].lower()
    assert str(date.today() - timedelta(days=1)) in body["message"]


def test_reading_still_works_after_expiry(api, monkeypatch, keys):
    """The deliberate limit on the lever.

    Convert while licensed, let the licence lapse, and the work already paid
    for is still readable. No new work is the pressure; losing old work would
    be a threat.
    """
    client = api.client
    _install(monkeypatch, keys, days=200)
    project_id = _ready(client)
    assert _convert(client, project_id).status_code == 202

    _install(monkeypatch, keys, days=-1, issued_days_ago=400)

    assert client.get(f"{PREFIX}/projects/{project_id}").status_code == 200
    assert client.get(f"{PREFIX}/projects/{project_id}/conversion").status_code == 200
    assert client.get(f"{PREFIX}/projects/{project_id}/report").status_code == 200


# --- when there is no licence at all ---------------------------------------------------


def test_a_deployment_with_no_licence_refuses_and_says_where_to_put_one(
    api, monkeypatch
):
    """A fresh install has a different problem from a lapsed one, and needs a
    different sentence: where the file goes, not who to call about renewing."""
    _unlicensed(monkeypatch)
    client = api.client
    body = _convert(client, _ready(client)).json()
    assert "LICENSE_FILE" in body["message"] or "no vendor key" in body["message"]
    assert "renew" not in body["message"].lower()


# --- the status route the screen reads -------------------------------------------------


def test_the_status_route_reports_a_good_licence_without_leaking_the_token(
    api, monkeypatch, keys
):
    """The screen needs to know the customer, the date and the days left. It
    never needs the signed token, and a token on the wire is a token in a log."""
    _install(monkeypatch, keys, days=100)
    body = api.client.get(f"{PREFIX}/license").json()

    assert body["licensed"] is True
    assert body["customer"] == "Northwind Analytics"
    assert body["days_remaining"] == 100
    # No field carries the token. Checked by shape rather than by name, so a
    # future field called something else cannot leak it either: a licence token
    # is two long base64 runs joined by a dot.
    import re

    token_shaped = re.compile(r"[A-Za-z0-9_-]{40,}\.[A-Za-z0-9_-]{40,}")
    for key, value in body.items():
        if isinstance(value, str):
            assert not token_shaped.search(value), f"{key} looks like the token"
    assert "BEGIN" not in str(body)
