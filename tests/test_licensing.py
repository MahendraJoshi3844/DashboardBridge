"""Licensing: a signed file, checked offline, that expires (`P7.1`).

The product is shipped and run in the customer's own environment, so the
commercial control has to work with no network at all - an air-gapped tenant is
a normal customer here, not an edge case. A licence is therefore a **signed
file**, not a call home: the vendor holds an Ed25519 private key and the
application ships only the public one.

## What this can and cannot do, said once and plainly

A customer who runs the deployment can bypass any check inside it. They have the
code, the process and the machine. **Licensing here is a commercial control for
honest customers, not a security boundary**, and building it as though it were
one would waste effort and mislead whoever reads it next.

What signing does buy, and it is the part that matters commercially:

* A licence cannot be **forged**. Changing the expiry date, the customer name or
  the enabled features breaks the signature, so a customer cannot quietly issue
  themselves another year.
* A licence cannot be **moved** without being noticed, because it names who it
  was issued to.
* Expiry is **checkable without a network**, so an offline deployment behaves
  the same as a connected one.

Clock rollback is the honest gap. Setting the machine's clock back a year makes
an expired licence look current, and nothing inside the process can prove
otherwise. The mitigation is a high-water mark - the latest time the application
has ever seen - so time appearing to move backwards is detected and refused.
That is a speed bump, not a lock, and it is described as one.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from engines.licensing import (
    ClockMovedBackwards,
    License,
    LicenseExpired,
    LicenseInvalid,
    generate_keypair,
    issue,
    verify,
)

TODAY = date(2026, 9, 5)


@pytest.fixture(scope="module")
def keys():
    """A vendor keypair. The private half never leaves the vendor."""
    return generate_keypair()


def _licence(keys, **overrides) -> str:
    private, _ = keys
    fields = {
        "customer": "Northwind Analytics",
        "issued": TODAY,
        "expires": TODAY + timedelta(days=365),
        "features": ("convert", "ai"),
        "seats": 25,
    }
    fields.update(overrides)
    return issue(private_key=private, **fields)


# --- what a valid licence does ------------------------------------------------------


def test_a_licence_the_vendor_issued_verifies(keys):
    _, public = keys
    licence = verify(_licence(keys), public_key=public, today=TODAY)
    assert isinstance(licence, License)
    assert licence.customer == "Northwind Analytics"


def test_the_licence_carries_what_was_bought(keys):
    _, public = keys
    licence = verify(_licence(keys), public_key=public, today=TODAY)
    assert licence.seats == 25
    assert licence.allows("convert")
    assert not licence.allows("something-not-sold")


def test_days_remaining_is_reported_so_renewal_is_never_a_surprise(keys):
    _, public = keys
    licence = verify(_licence(keys), public_key=public, today=TODAY)
    assert licence.days_remaining(TODAY) == 365
    assert licence.days_remaining(TODAY + timedelta(days=300)) == 65


def test_a_licence_close_to_expiry_says_so_before_it_stops_working(keys):
    """A licence that works on Friday and refuses on Monday with no warning is
    a support call, not a renewal."""
    _, public = keys
    licence = verify(_licence(keys), public_key=public, today=TODAY)
    assert not licence.expiring_soon(TODAY)
    assert licence.expiring_soon(TODAY + timedelta(days=360))


# --- what a licence cannot be -------------------------------------------------------


def test_a_licence_signed_by_someone_else_is_refused(keys):
    """The whole point of signing. Another keypair is what a customer would
    have if they tried to issue their own."""
    _, public = keys
    other_private, _ = generate_keypair()
    forged = issue(
        private_key=other_private,
        customer="Northwind Analytics",
        issued=TODAY,
        expires=TODAY + timedelta(days=3650),
        features=("convert",),
        seats=999,
    )
    with pytest.raises(LicenseInvalid):
        verify(forged, public_key=public, today=TODAY)


def test_editing_the_expiry_date_breaks_the_signature(keys):
    """The specific attack worth stopping: a customer giving themselves another
    year by editing a field."""
    import base64
    import json

    private, public = keys
    token = _licence(keys)
    payload_b64, signature = token.split(".", 1)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    payload["expires"] = "2099-01-01"
    tampered = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        + "."
        + signature
    )
    with pytest.raises(LicenseInvalid):
        verify(tampered, public_key=public, today=TODAY)


@pytest.mark.parametrize(
    "token", ["", "not-a-licence", "a.b", "....", "eyJhIjoxfQ.zzzz"]
)
def test_a_malformed_licence_is_refused_rather_than_crashing(token, keys):
    """A licence file is typed in or pasted by a person. Every wrong shape has
    to come back as a refusal they can act on, not a stack trace."""
    _, public = keys
    with pytest.raises(LicenseInvalid):
        verify(token, public_key=public, today=TODAY)


# --- expiry -------------------------------------------------------------------------


def test_an_expired_licence_is_refused_and_names_the_date(keys):
    _, public = keys
    # Issued last year and expired yesterday - which is what an expired
    # licence actually looks like. `issue` refuses to mint one that expires
    # before it was issued, so the first version of this test asked for an
    # impossible licence and was reporting that safeguard as a failure.
    token = _licence(
        keys, issued=TODAY - timedelta(days=400), expires=TODAY - timedelta(days=1)
    )
    with pytest.raises(LicenseExpired) as raised:
        verify(token, public_key=public, today=TODAY)
    assert "2026-09-04" in str(raised.value)


def test_a_licence_is_valid_on_its_last_day(keys):
    """Off-by-one here is a customer locked out a day early, which is the one
    licensing bug guaranteed to reach the vendor by telephone."""
    _, public = keys
    last_day = TODAY + timedelta(days=30)
    licence = verify(_licence(keys, expires=last_day), public_key=public, today=last_day)
    assert licence.days_remaining(last_day) == 0


def test_a_licence_issued_in_the_future_is_refused(keys):
    """Either the clock is wrong or the licence is. Both need a person."""
    _, public = keys
    token = _licence(keys, issued=TODAY + timedelta(days=5))
    with pytest.raises(LicenseInvalid):
        verify(token, public_key=public, today=TODAY)


def test_the_expiry_message_says_what_to_do_next(keys):
    """An expiry that only says "expired" sends someone to the wrong person."""
    _, public = keys
    token = _licence(
        keys, issued=TODAY - timedelta(days=400), expires=TODAY - timedelta(days=1)
    )
    with pytest.raises(LicenseExpired) as raised:
        verify(token, public_key=public, today=TODAY)
    assert "renew" in str(raised.value).lower()


# --- the clock ----------------------------------------------------------------------


def test_time_going_backwards_is_detected(keys):
    """The honest gap in offline licensing, and its speed bump.

    Nothing inside the process can prove the machine's clock is right. What it
    can notice is time appearing to move backwards from the latest it has ever
    seen, which is what setting the clock back to un-expire a licence looks
    like from in here.
    """
    _, public = keys
    token = _licence(keys)
    with pytest.raises(ClockMovedBackwards):
        verify(token, public_key=public, today=TODAY, high_water=TODAY + timedelta(days=40))


def test_the_same_day_is_not_backwards(keys):
    """Checked twice in a day must not trip the guard."""
    _, public = keys
    licence = verify(_licence(keys), public_key=public, today=TODAY, high_water=TODAY)
    assert licence.customer


def test_the_clock_guard_is_described_as_a_speed_bump_not_a_lock():
    """Stated in the module, so the next person does not mistake it for one.

    An honest limit written down is a design decision; the same limit left
    unwritten is a claim the product cannot support.
    """
    import engines.licensing as module

    text = (module.__doc__ or "").lower()
    assert "clock" in text
    assert "not a security boundary" in text


# --- the private key -----------------------------------------------------------------


def _files_holding_a_private_key(root) -> list[str]:
    """Files under `root` that contain an actual PEM private key block.

    A whole block - the opening line, base64 body, and closing line - not just
    the opening words. The first version matched the words alone and reported
    *this file* as an offender, because the marker strings are written here.
    A guard that flags itself teaches everyone to ignore it.

    The pattern is assembled from fragments so that this file never contains a
    complete marker to be found in the first place.
    """
    import re

    dashes = "-" * 5
    opening = re.escape(dashes) + r"BEGIN [A-Z ]*PRIVATE KEY" + re.escape(dashes)
    closing = re.escape(dashes) + r"END [A-Z ]*PRIVATE KEY" + re.escape(dashes)
    block = re.compile(opening + r"[A-Za-z0-9+/=\s]{40,}?" + closing)

    skip_suffixes = {".png", ".ico", ".woff", ".woff2", ".zip", ".xls", ".xlsx", ".pyc"}
    found: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.parts)
        if ".git" in parts or "node_modules" in parts or "__pycache__" in parts:
            continue
        if path.suffix.lower() in skip_suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if block.search(text):
            found.append(str(path.relative_to(root)))
    return found


def test_the_private_key_scan_actually_finds_one(tmp_path, keys):
    """The control. A scan that cannot find a key is not a guard.

    A real vendor key is planted and the scan has to see it - otherwise the
    repository check below passes because the pattern is wrong, which is the
    failure mode that would end the licensing scheme quietly.
    """
    private, _ = keys
    (tmp_path / "vendor.pem").write_text(private, encoding="utf-8")
    assert _files_holding_a_private_key(tmp_path) == ["vendor.pem"]


def test_no_private_key_is_committed_to_the_repository():
    """The one mistake that ends the licensing scheme.

    A private key in the repository means every customer can issue themselves a
    perpetual licence, and no amount of signing helps afterwards.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert _files_holding_a_private_key(root) == []
