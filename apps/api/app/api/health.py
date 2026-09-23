"""Health and capability. The UI reads this to know what it may offer."""

from __future__ import annotations

from dashboardbridge_contracts import HealthResponse
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    config = settings()
    return HealthResponse(
        status="ok",
        version=config.version,
        privacy_mode=config.privacy_mode,
        # Absent, not degraded: with no provider the UI hides AI entirely
        # rather than offering something that will fail.
        ai_available=config.ai_provider.value != "none",
    )
