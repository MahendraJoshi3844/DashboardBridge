"""`GET /directions`: which migrations this deployment can run, and why not the rest.

The web app draws its migration cards and sidebar from this, so a customer with
only some engines sees exactly those enabled - and a reason on the others.
"""

from __future__ import annotations

from dashboardbridge_contracts import DirectionList
from fastapi import APIRouter, Depends

from app.api.accounts import current_user
from app.core.directions import grants_of
from app.core.licensing import status as license_status
from app.db.models import User
from engines.conversion import directions as registry

router = APIRouter(tags=["directions"])


@router.get("/directions", response_model=DirectionList)
def list_directions(user: User = Depends(current_user)) -> DirectionList:
    """For the signed-in person: an administrator sees every installed, licensed
    product available; everyone else also needs an administrator's grant."""
    licence = license_status().license
    features = list(licence.features) if licence is not None else None
    return DirectionList(directions=registry.statuses(features, grants_of(user)))
