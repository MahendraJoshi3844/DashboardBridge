"""A licence the vendor signs and the deployment checks offline (`P7.1`).

The product ships and runs in the customer's own environment. That is the whole
premise - a workbook never leaves their machine - so the commercial control has
to work with no network at all: an air-gapped customer is a normal customer
here, not an edge case.

So a licence is a **signed file**, not a call home. The vendor holds an Ed25519
private key; the application ships only the public one and can therefore check a
licence but never mint one.

## What this buys, and what it does not

**It is not a security boundary.** A customer who runs the deployment has the
code, the process and the machine, and can bypass any check inside it. This is a
commercial control for honest customers - the great majority - and building it
as though it were unbreakable would waste effort and mislead whoever reads this
next.

What signing does buy is the part that matters commercially:

* A licence cannot be **forged**. Editing the expiry, the customer name or the
  feature list breaks the signature, so nobody quietly issues themselves another
  year.
* A licence names **who it was issued to**, so it cannot be passed around
  without that being visible.
* Expiry is **checkable with no network**, so an offline deployment behaves
  exactly like a connected one.

**The clock is the honest gap.** Setting the machine's clock back makes an
expired licence look current, and nothing inside this process can prove
otherwise. `high_water` is the mitigation: the latest date the application has
ever seen. Time appearing to move backwards from it is what a rollback looks
like from in here, and it is refused. That is a speed bump, not a lock.

## Format

`base64url(payload json) . base64url(signature)` - one line, no newlines, safe
to paste into a form or an environment variable, and readable enough that a
support engineer can see the expiry without a tool.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

__all__ = [
    "ClockMovedBackwards",
    "License",
    "LicenseError",
    "LicenseExpired",
    "LicenseInvalid",
    "generate_keypair",
    "issue",
    "verify",
]

#: How long before expiry the application starts saying so. A licence that
#: works on Friday and refuses on Monday with no warning is a support call
#: rather than a renewal.
WARN_WITHIN_DAYS = 30


class LicenseError(RuntimeError):
    """Base for everything here, so a caller can catch one thing."""


class LicenseInvalid(LicenseError):
    """Not a licence this vendor issued, or not a licence at all."""


class LicenseExpired(LicenseError):
    """Genuine, and past its date."""


class ClockMovedBackwards(LicenseError):
    """The machine's clock is earlier than a date this deployment has seen."""


@dataclass(frozen=True)
class License:
    customer: str
    issued: date
    expires: date
    features: tuple[str, ...]
    seats: int

    def allows(self, feature: str) -> bool:
        return feature in self.features

    def days_remaining(self, today: date) -> int:
        """Whole days left, counting the expiry day itself as usable.

        Zero on the last valid day, not the day after. An off-by-one here locks
        a customer out a day early, which is the one licensing bug guaranteed
        to reach the vendor by telephone.
        """
        return (self.expires - today).days

    def expiring_soon(self, today: date) -> bool:
        return 0 <= self.days_remaining(today) <= WARN_WITHIN_DAYS


def generate_keypair() -> tuple[str, str]:
    """A new vendor keypair as `(private_pem, public_pem)`.

    Run once, by the vendor, off this machine. The private half never enters
    the repository or a deployment - `tests/test_licensing.py` fails the build
    if a private key is ever committed, because that single mistake ends the
    scheme for every customer at once.
    """
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    # `urlsafe_b64decode` needs the padding the encoder stripped.
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue(
    *,
    private_key: str,
    customer: str,
    issued: date,
    expires: date,
    features: Iterable[str],
    seats: int,
) -> str:
    """Mint a licence. Vendor side only - the deployment has no private key.

    The payload is sorted and separator-normalised so the same inputs always
    produce the same bytes: a licence that differed run to run could not be
    compared, diffed, or recognised as one already issued.
    """
    if expires < issued:
        raise LicenseInvalid(
            f"A licence cannot expire ({expires}) before it is issued ({issued})."
        )
    key = serialization.load_pem_private_key(private_key.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise LicenseInvalid("The signing key is not an Ed25519 private key.")

    payload = json.dumps(
        {
            "customer": customer,
            "issued": issued.isoformat(),
            "expires": expires.isoformat(),
            "features": sorted(features),
            "seats": int(seats),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"{_b64(payload)}.{_b64(key.sign(payload))}"


def verify(
    token: str,
    *,
    public_key: str,
    today: date,
    high_water: date | None = None,
) -> License:
    """Check a licence and return it, or raise saying which thing was wrong.

    The order is deliberate: **signature first**. A tampered licence is not
    "expired", and telling someone their forged licence has run out sends them
    to renew something that was never valid.

    `high_water` is the latest date this deployment has recorded. Passing it
    turns on the clock-rollback check; leaving it `None` checks the licence
    alone, which is right for a vendor-side tool with no deployment history.
    """
    payload = _parse(token, public_key)

    try:
        issued = date.fromisoformat(payload["issued"])
        expires = date.fromisoformat(payload["expires"])
        licence = License(
            customer=str(payload["customer"]),
            issued=issued,
            expires=expires,
            features=tuple(payload.get("features") or ()),
            seats=int(payload.get("seats", 0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LicenseInvalid(
            "The licence is signed but does not contain the expected fields. "
            "Ask for a replacement licence file."
        ) from exc

    # Before expiry, because a clock that has moved makes every date suspect and
    # "expired" would be the wrong thing to tell someone.
    if high_water is not None and today < high_water:
        raise ClockMovedBackwards(
            f"This machine's clock reads {today}, and this installation has "
            f"already seen {high_water}. The licence cannot be checked until "
            "the clock is correct."
        )

    if issued > today:
        raise LicenseInvalid(
            f"This licence starts on {issued} and today is {today}. Either the "
            "machine's clock is wrong or the licence is not the right one."
        )

    if expires < today:
        raise LicenseExpired(
            f"The licence for {licence.customer} ran out on {expires}. "
            "Converting is switched off until it is renewed - ask your supplier "
            "for a new licence file. Everything already converted stays "
            "readable."
        )

    return licence


def _parse(token: str, public_key: str) -> dict:
    """Split, check the signature, and return the payload.

    Every malformed shape becomes `LicenseInvalid`. A licence is typed in or
    pasted by a person, so the wrong shape has to come back as something they
    can act on rather than as a stack trace out of a base64 decoder.
    """
    try:
        key = serialization.load_pem_public_key(public_key.encode())
    except Exception as exc:  # noqa: BLE001 - any failure here is the same fact
        raise LicenseInvalid("This build has no usable licence key.") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise LicenseInvalid("This build's licence key is not an Ed25519 key.")

    if token.count(".") != 1:
        raise LicenseInvalid(
            "That does not look like a licence file. It should be one line "
            "containing a single dot."
        )
    payload_b64, signature_b64 = token.split(".", 1)
    if not payload_b64 or not signature_b64:
        raise LicenseInvalid("The licence file is incomplete.")

    try:
        payload_raw = _unb64(payload_b64)
        signature = _unb64(signature_b64)
    except (ValueError, TypeError) as exc:
        raise LicenseInvalid("The licence file is damaged.") from exc

    try:
        key.verify(signature, payload_raw)
    except InvalidSignature as exc:
        raise LicenseInvalid(
            "This licence was not issued for this product, or it has been "
            "edited since it was issued. Ask your supplier for the original "
            "file."
        ) from exc

    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError as exc:
        raise LicenseInvalid("The licence file is damaged.") from exc
    if not isinstance(payload, dict):
        raise LicenseInvalid("The licence file is damaged.")
    return payload
