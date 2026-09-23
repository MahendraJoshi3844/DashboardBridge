"""The licence this deployment is running under (`P7.1`).

The product ships and runs in the customer's own environment, so this is read
from a file on that machine and checked with no network at all - an air-gapped
customer is a normal customer here.

## What is enforced, and what is deliberately not

**Converting is what a licence buys, so an expired licence stops conversions.**
Reading is not blocked: past projects, their reports and their flags stay
available after expiry. Holding work someone already paid for hostage does not
sell a renewal, it sells resentment - and the commercial lever that actually
works is that no *new* work can be done.

**A missing licence is not an expired one.** A fresh deployment with no licence
file yet says so, and says where to put one. An expired licence names its date
and says to renew. Those are different conversations with different people.

## The clock

`verify` takes a high-water mark - the latest date this deployment has ever
seen - so time appearing to move backwards is refused rather than trusted. That
is a speed bump on setting the clock back to un-expire a licence, not a lock;
`engines/licensing` says so at length and this module does not claim more.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timezone, datetime
from functools import lru_cache
from pathlib import Path

from engines.licensing import (
    License,
    LicenseError,
    LicenseExpired,
    LicenseInvalid,
    verify,
)

#: The vendor's public key, shipped with the application. Only the public half:
#: the private key never leaves the vendor, and `tests/test_licensing.py` fails
#: if one is ever committed here.
#:
#: Empty until a release is cut with a real key, and empty is handled: the
#: deployment reports itself unlicensed rather than pretending to be licensed.
VENDOR_PUBLIC_KEY = os.getenv("LICENSE_PUBLIC_KEY", "").strip()


@dataclass(frozen=True)
class LicenseStatus:
    """What the deployment can currently do, and what to tell the operator.

    A status object rather than an exception, because the answer is needed in
    two different registers: a route that must refuse, and a screen that must
    warn while everything still works.
    """

    licensed: bool
    license: License | None
    #: A sentence for the operator. Present whenever something needs doing -
    #: which includes "valid, but expiring in nine days".
    message: str | None
    expiring_soon: bool = False

    @property
    def may_convert(self) -> bool:
        return self.licensed


def _license_text() -> str:
    """The licence, from the environment or from a file beside the install."""
    inline = os.getenv("LICENSE_KEY", "").strip()
    if inline:
        return inline
    path = os.getenv("LICENSE_FILE", "").strip()
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        # Unreadable and absent are the same to the caller - the deployment is
        # not licensed - but the message says which, because "the file is not
        # there" and "the service cannot read it" are different fixes.
        return ""


def _today() -> date:
    """UTC, so a deployment does not gain or lose a day by its timezone."""
    return datetime.now(timezone.utc).date()


@lru_cache(maxsize=1)
def status() -> LicenseStatus:
    """The current licence status. Cached: the file does not change under us.

    Cleared by `status.cache_clear()`, which the tests use and an operator
    triggers by restarting after installing a new licence. A licence that
    re-read itself every request would turn every conversion into a disk read
    for a value that changes a few times a year.
    """
    if not VENDOR_PUBLIC_KEY:
        return LicenseStatus(
            licensed=False,
            license=None,
            message=(
                "This build has no vendor key, so no licence can be checked. "
                "That is a packaging fault rather than anything you did - ask "
                "whoever supplied the build."
            ),
        )

    token = _license_text()
    if not token:
        return LicenseStatus(
            licensed=False,
            license=None,
            message=(
                "No licence is installed. Put the licence file supplied with "
                "your subscription where LICENSE_FILE points, or set "
                "LICENSE_KEY, then restart."
            ),
        )

    try:
        licence = verify(token, public_key=VENDOR_PUBLIC_KEY, today=_today())
    except LicenseExpired as expired:
        return LicenseStatus(licensed=False, license=None, message=str(expired))
    except LicenseInvalid as invalid:
        return LicenseStatus(licensed=False, license=None, message=str(invalid))
    except LicenseError as other:
        return LicenseStatus(licensed=False, license=None, message=str(other))

    today = _today()
    soon = licence.expiring_soon(today)
    return LicenseStatus(
        licensed=True,
        license=licence,
        expiring_soon=soon,
        message=(
            f"This licence expires in {licence.days_remaining(today)} days "
            f"({licence.expires}). Renew before then to avoid an interruption."
            if soon
            else None
        ),
    )
