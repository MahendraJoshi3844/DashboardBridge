"""The three privacy modes, and the one that does not exist yet (`P7.8`).

`STANDARD` and `LOCAL_ONLY` are real: the router honours them, the request
contract rejects a remote provider under `LOCAL_ONLY`, and
`test_local_only_egress.py` is the mechanical evidence for the second.

`ENTERPRISE_PRIVATE` is not. `09-security-spec.md` defines it as *"configured
endpoint, egress logged"* and the agent brief as *"egress logged and
auditable"*. Nothing logs anything. Selecting it today gets `STANDARD`
behaviour under a name that promises an audit trail — which is worse than not
offering the mode at all, because a regulated tenant would choose it *for* the
audit trail and receive a claim rather than a log.

So it is refused at configuration, with a sentence saying what is missing. That
is the project's own rule applied to itself: never claim more than the evidence
supports. The refusal is removed by implementing the log, not by deleting these
tests.
"""

from __future__ import annotations

import pytest

from dashboardbridge_contracts.enums import PrivacyMode


# --- the modes that are real ----------------------------------------------------


def test_local_only_is_what_you_get_when_nothing_is_configured(monkeypatch):
    """The safe mode is the default, not the one you have to remember."""
    from app.core.config import settings

    monkeypatch.delenv("PRIVACY_MODE", raising=False)
    settings.cache_clear()
    assert settings().privacy_mode is PrivacyMode.LOCAL_ONLY


def test_standard_is_accepted(monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv("PRIVACY_MODE", "standard")
    settings.cache_clear()
    assert settings().privacy_mode is PrivacyMode.STANDARD


# --- the mode that is not -------------------------------------------------------


def test_enterprise_private_is_refused_rather_than_silently_standard(monkeypatch):
    """It promises an audit trail that does not exist.

    Behaving as `STANDARD` under this name is the failure the whole project is
    written against: a claim the evidence does not support, made silently, to
    the one user who chose the mode because of the claim.
    """
    from app.core.config import settings

    monkeypatch.setenv("PRIVACY_MODE", "enterprise_private")
    settings.cache_clear()

    with pytest.raises(ValueError) as raised:
        settings()

    assert "audit" in str(raised.value).lower()


def test_the_refusal_says_what_would_have_to_exist(monkeypatch):
    """A refusal with no route out of it is an outage, not a decision."""
    from app.core.config import settings

    monkeypatch.setenv("PRIVACY_MODE", "enterprise_private")
    settings.cache_clear()

    with pytest.raises(ValueError) as raised:
        settings()

    message = str(raised.value)
    assert "local_only" in message and "standard" in message


def test_the_mode_still_exists_in_the_contract(monkeypatch):
    """Refused at configuration, not removed from the vocabulary.

    Deleting the value would be a breaking contract change and would lose the
    design; the web app already renders it, and `P7.2`'s secret provider is what
    it is waiting on. The enum is the plan, the refusal is the current state.
    """
    assert PrivacyMode.ENTERPRISE_PRIVATE.value == "enterprise_private"


def test_the_refusal_is_removed_by_building_the_log_not_by_editing_this_test(
    monkeypatch,
):
    """A canary, so the refusal cannot outlive its reason.

    If anything ever writes an egress audit log, this fails and points at the
    refusal to be lifted - rather than the refusal quietly remaining in place
    once the feature it was waiting for arrives.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    implemented = any(
        "egress_log" in path.read_text(encoding="utf-8")
        for path in (root / "engines").rglob("*.py")
        if "__pycache__" not in path.parts
    )
    assert not implemented, (
        "an egress log exists now; lift the ENTERPRISE_PRIVATE refusal in "
        "app/core/config.py and replace these tests with ones that assert the "
        "log is written"
    )
