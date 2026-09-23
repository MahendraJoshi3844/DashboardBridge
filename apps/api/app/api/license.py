"""The licence status this deployment is running under (`P7.1`).

Read-only, and deliberately never returns the licence token itself. The screen
needs the customer, the expiry and the days left; it never needs the signed
string, and a token on the wire is a token in somebody's proxy log.

There is no route to *install* a licence. Installing one is putting a file on
the machine and restarting - which is an operator's job with the operator's
permissions, not something reachable from a browser. An endpoint that accepted a
licence would be an endpoint that accepted a forged one to test against.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.licensing import status
from dashboardbridge_contracts import LicenseStatusResponse

router = APIRouter(tags=["license"])


@router.get("/license", response_model=LicenseStatusResponse)
def read_license() -> LicenseStatusResponse:
    from datetime import date

    current = status()
    licence = current.license
    if licence is None:
        return LicenseStatusResponse(
            licensed=False, message=current.message, expiring_soon=False
        )
    return LicenseStatusResponse(
        licensed=True,
        customer=licence.customer,
        expires=str(licence.expires),
        days_remaining=licence.days_remaining(date.today()),
        seats=licence.seats,
        features=sorted(licence.features),
        expiring_soon=current.expiring_soon,
        message=current.message,
    )
