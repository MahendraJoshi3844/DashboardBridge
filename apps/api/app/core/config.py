"""Configuration from the environment. Never a hard-coded credential (§53)."""

from __future__ import annotations

import os
from functools import lru_cache

from dashboardbridge_contracts import PrivacyMode, ProviderKind
from pydantic import BaseModel

from app.core.secrets import build_provider


class Settings(BaseModel):
    app_env: str = "development"
    version: str = "0.1.0"
    privacy_mode: PrivacyMode = PrivacyMode.LOCAL_ONLY
    ai_provider: ProviderKind = ProviderKind.NONE
    max_upload_size_mb: int = 500
    #: A ceiling on runaway cost, not a quota. Generous on purpose: a
    #: person working normally must never meet it. 0 turns the class off.
    rate_limit_write_per_minute: int = 60
    rate_limit_read_per_minute: int = 600
    #: Whether an unscanned upload may be stored. False for a local install,
    #: which has no scanner and needs none; true is the setting a regulated
    #: deployment turns on so a missing scanner fails loudly (`P7.5`).
    require_malware_scan: bool = False
    artifact_storage_dir: str = ""
    #: Provider configuration. The key is read here and never leaves the
    #: process: there is no API route that returns it or accepts one, because
    #: until `P7.2` there is nowhere safe to put a submitted credential.
    ai_api_key: str = ""
    ai_base_url: str = ""
    ai_model: str = ""
    ai_host: str = "127.0.0.1"
    #: 0 means "whatever the provider's own default is". The port is not
    #: restated here: one constant in two places is one that drifts, and this
    #: module has no business knowing which port a runtime happens to use.
    ai_port: int = 0
    #: Seconds to wait for a model's answer. 0 keeps the provider's default.
    ai_timeout_s: float = 0

    @property
    def local_only(self) -> bool:
        return self.privacy_mode is PrivacyMode.LOCAL_ONLY


def _privacy_mode(raw: str) -> PrivacyMode:
    """The configured mode, refusing the one that does not exist yet (`P7.8`).

    `ENTERPRISE_PRIVATE` is specified as "configured endpoint, egress logged and
    auditable". Nothing logs anything, so selecting it would get `STANDARD`
    behaviour under a name that promises an audit trail - and a regulated tenant
    would choose it *for* the audit trail and receive a claim instead of a log.

    Refusing is the project's own rule applied to itself: never claim more than
    the evidence supports. The value stays in the contract, because the enum is
    the plan and this is the current state; the refusal is lifted by writing the
    log, not by deleting it.
    """
    mode = PrivacyMode(raw)
    if mode is PrivacyMode.ENTERPRISE_PRIVATE:
        raise ValueError(
            "enterprise_private promises an egress audit log that does not "
            "exist yet, and running without one would claim an audit trail "
            "this build cannot produce. Use local_only, which keeps everything "
            "on this machine, or standard, which is honest about sending data "
            "to a configured provider."
        )
    return mode


@lru_cache
def settings() -> Settings:
    """LOCAL_ONLY is the default deliberately: the safe mode is the one you get
    when nothing is configured, not the one you have to remember to turn on."""
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        privacy_mode=_privacy_mode(os.getenv("PRIVACY_MODE", "local_only")),
        ai_provider=ProviderKind(os.getenv("AI_PROVIDER", "none")),
        max_upload_size_mb=int(os.getenv("MAX_UPLOAD_SIZE_MB", "500")),
        rate_limit_write_per_minute=int(
            os.getenv("RATE_LIMIT_WRITE_PER_MINUTE", "60")
        ),
        rate_limit_read_per_minute=int(
            os.getenv("RATE_LIMIT_READ_PER_MINUTE", "600")
        ),
        require_malware_scan=os.getenv("REQUIRE_MALWARE_SCAN", "").lower()
        in {"1", "true", "yes"},
        artifact_storage_dir=os.getenv("ARTIFACT_STORAGE_DIR", ""),
        # Through the secret provider (`P7.2`), not straight from the
        # environment: `env` is still the default and still reads the same
        # variable, but the seam exists so a deployment can move it.
        ai_api_key=build_provider().get("AI_API_KEY") or "",
        ai_base_url=os.getenv("AI_BASE_URL", ""),
        ai_model=os.getenv("AI_MODEL", ""),
        ai_host=os.getenv("AI_HOST", "127.0.0.1"),
        ai_port=int(os.getenv("AI_PORT", "0")),
        ai_timeout_s=float(os.getenv("AI_TIMEOUT_S", "0")),
    )
