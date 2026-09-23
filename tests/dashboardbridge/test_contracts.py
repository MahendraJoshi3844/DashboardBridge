"""Contracts carry the product's rules, so the rules are tested here.

These are not shape tests. Each one pins a decision from
docs/dashboardbridge/00-decisions.md that a later change could quietly undo.
"""

import pytest
from pydantic import ValidationError

from dashboardbridge_contracts import (
    CanonicalModel,
    Column,
    ConversionRequest,
    CreateProjectRequest,
    NumericalValidation,
    Platform,
    PrivacyMode,
    ProviderKind,
    Validation,
)
from dashboardbridge_contracts.enums import ConversionMethod, ConversionStatus, Severity


# --- ADR-004: method, status and severity are three axes -------------------


def test_an_item_can_be_ai_required_yet_end_up_manual():
    """The case a single enum cannot express, and §62 requires us to report."""
    from dashboardbridge_contracts import ConversionFlag
    from dashboardbridge_contracts.enums import Stage

    flag = ConversionFlag(
        item="Orders.Sales Forecast",
        stage=Stage.TRANSLATE,
        method=ConversionMethod.MANUAL,
        status=ConversionStatus.AI_REQUIRED,
        severity=Severity.MANUAL,
        reason="User declined AI; needs a hand-written measure.",
    )
    assert flag.status is ConversionStatus.AI_REQUIRED
    assert flag.method is ConversionMethod.MANUAL


# --- ADR-003: numerical validation is never claimed ------------------------


def test_numerical_validation_defaults_to_unmeasured():
    assert NumericalValidation().measured is False


def test_numerical_validation_states_why_it_was_not_measured():
    assert "executing both dashboards" in NumericalValidation().reason


def test_a_validation_with_no_measured_categories_has_no_score():
    from uuid import uuid4

    from dashboardbridge_contracts.enums import JobStatus, Verdict

    result = Validation(
        validation_id=uuid4(), status=JobStatus.COMPLETED, verdict=Verdict.UNVERIFIED
    )
    assert result.score is None, "an unmeasured conversion must not carry a score"


# --- request validation refuses contradictions rather than guessing --------


def test_ai_enabled_without_a_provider_is_rejected():
    with pytest.raises(ValidationError, match="requires a provider"):
        ConversionRequest(ai_enabled=True, provider=ProviderKind.NONE)


def test_local_only_forbids_a_remote_provider():
    """The offline guarantee is enforced in the contract, not by convention."""
    with pytest.raises(ValidationError, match="local_only"):
        ConversionRequest(
            ai_enabled=True,
            provider=ProviderKind.OPENAI_COMPATIBLE,
            privacy_mode=PrivacyMode.LOCAL_ONLY,
        )


def test_local_only_permits_a_loopback_provider():
    request = ConversionRequest(
        ai_enabled=True,
        provider=ProviderKind.OLLAMA,
        privacy_mode=PrivacyMode.LOCAL_ONLY,
    )
    assert request.provider is ProviderKind.OLLAMA


def test_a_project_cannot_convert_a_platform_to_itself():
    with pytest.raises(ValidationError, match="must differ"):
        CreateProjectRequest(
            source_platform=Platform.TABLEAU,
            target_platform=Platform.TABLEAU,
            name="nonsense",
        )


# --- the canonical model stays neutral -------------------------------------


def test_undeclared_fields_are_refused():
    """An adapter smuggling platform detail through is how neutrality dies."""
    with pytest.raises(ValidationError):
        Column(id="t.c", name="c", shelf="rows")  # type: ignore[call-arg]


def test_absent_grain_means_undetermined_not_row_level():
    """None is 'we could not tell', which is refused - never a default guess."""
    assert Column(id="t.c", name="c").grain is None


def test_display_name_prefers_caption():
    assert Column(id="t.c", name="internal", caption="Sales").display_name == "Sales"


def test_a_model_is_frozen_once_built():
    model = CanonicalModel(source_platform=Platform.TABLEAU)
    with pytest.raises(ValidationError):
        model.name = "changed"  # type: ignore[misc]


def test_the_wire_format_is_json_serialisable():
    model = CanonicalModel(source_platform=Platform.TABLEAU, name="Superstore")
    assert model.model_dump_json().startswith("{")
