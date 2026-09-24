"""The workspace assistant: one step of a Run-menu job per request.

The client runs a job - Optimize Model, Full Health Check, Batch Fix All - as a
sequence of these steps and shows each as it returns, so "Task 2/4" on the
screen means the second request came back rather than a timer advancing.

Deterministic steps first, always. The model is reached only by `draft_dax`
(for calculations the converter held), `summarize` and `chat`, only through the
router, and never to change anything: every proposal is offered to a person.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from dashboardbridge_contracts import (
    AssistantMessage,
    AssistantProposal,
    AssistantStepRequest,
    AssistantStepResult,
)
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.proposals import _conversion, _refused
from app.api.settings import _ai_settings
from app.api.workspace import _held, _power_bi_only, _versions
from app.core.db import get_session
from app.core.errors import ApiException
from app.services import assistant as rules
from app.services import workspace as ws
from app.services.artifact_store import ArtifactStore, get_artifact_store
from dashboardbridge_contracts.enums import ErrorCategory
from engines.ai.proposal import vet
from engines.ai.router import AdviceRequest, Disposition, advise, route
from engines.conversion.ai_requests import policy_for, request_for

logger = logging.getLogger(__name__)
router = APIRouter(tags=["assistant"])

#: Why nothing could be asked at all - the same answer for every item.
_NO_MODEL = {
    Disposition.NOT_ENABLED,
    Disposition.NO_PROVIDER,
    Disposition.REFUSED_BY_PRIVACY,
    Disposition.PROVIDER_UNAVAILABLE,
    Disposition.NO_PROMPT,
}

_TITLES = {
    "draft_dax": "Fix DAX",
    "summarize": "AI summary",
    "chat": "AI Assistant",
}


def _context(session: Session, project_id: UUID, store: ArtifactStore) -> rules.Context:
    rows = _versions(session, project_id)
    files = ws.unzip(store.read(rows[-1].storage_key))
    tables = ws.read_tables(files)
    written = {(t.name, m.name) for t in tables for m in t.measures}
    return rules.Context(
        tables=tables,
        pages=ws.read_report(files),
        relationships=rules.relationships_of(files),
        held=[h for h in _held(session, project_id) if (h.table, h.name) not in written],
    )


def _ai_off_message(reason: str) -> AssistantMessage:
    return AssistantMessage(role="system", text=f"No model was asked: {reason}")


def _draft_dax(
    session: Session, project_id: UUID, ctx: rules.Context, items: list[str]
) -> AssistantStepResult:
    """Drafts for held calculations, through the same router and checks as P4.

    A draft that does not survive `vet` is reported and dropped. One that does
    becomes a proposal a person may put into their draft changes as a measure.
    """
    held = {h.item: h for h in ctx.held}
    targets = [h for h in ctx.held if not items or h.item in items]
    if not targets:
        return AssistantStepResult(
            step="draft_dax",
            title=_TITLES["draft_dax"],
            messages=[AssistantMessage(role="system", text="No held calculation to draft: every calculation is already in the model.")],
        )

    ai = _ai_settings()
    conversion = _conversion(session, project_id)
    if conversion.model is None:
        raise ApiException(
            ErrorCategory.CONVERSION_ERROR,
            "The conversion did not return its model, so there is nothing to describe to a model.",
            detail=f"conversion for {project_id} carries no model",
            status_code=409,
        )
    policy = policy_for(conversion.model)
    reasons = dict(_refused(conversion))
    messages: list[AssistantMessage] = []
    proposals: list[AssistantProposal] = []

    for entry in targets:
        column_id = next((cid for cid in reasons if cid == entry.item or cid.endswith(f".{entry.name}")), entry.item)
        request = request_for(conversion.model, column_id, reasons.get(column_id, entry.reason))
        routed = asyncio.run(route(request, ai))
        if routed.draft is None:
            if routed.disposition in _NO_MODEL:
                # Nothing to ask, for every item alike: say so once and stop.
                messages.append(_ai_off_message(routed.reason))
                break
            messages.append(AssistantMessage(role="system", text=f"{entry.item}: {routed.reason}"))
            continue
        verdict = vet(
            routed.draft.text,
            request,
            policy,
            model=routed.draft.model,
            prompt_version=routed.draft.prompt_version,
        )
        if verdict.proposal is None:
            messages.append(
                AssistantMessage(
                    role="system",
                    text=f"{entry.item}: the model's draft was discarded by the checks - {verdict.reason}",
                )
            )
            continue
        expression = verdict.proposal.target_expression
        problems = rules.draft_problems(expression, entry.source, ctx)
        if problems:
            messages.append(
                AssistantMessage(
                    role="system",
                    text=f"{entry.item}: the model's draft was discarded - {'; '.join(problems)}. Draft: {expression}",
                )
            )
            continue
        proposals.append(
            AssistantProposal(
                kind="measure",
                table=held[entry.item].table if entry.item in held else entry.table,
                name=entry.name,
                expression=expression,
                current=entry.source,
                reason=(
                    "Drafted by a model from the Tableau source and passed the proposal "
                    "checks. Review it before applying: it is written as a measure."
                ),
                origin="model",
                model=routed.draft.model,
            )
        )
    messages.insert(
        0,
        AssistantMessage(
            role="system",
            text=f"Asked for drafts of {len(targets)} held calculation{'s' if len(targets) != 1 else ''}; {len(proposals)} passed the checks.",
        ),
    )
    return AssistantStepResult(step="draft_dax", title=_TITLES["draft_dax"], messages=messages, proposals=proposals)


def _advice(step: str, ctx: rules.Context, question: str = "") -> AssistantStepResult:
    operation = "workspace_chat" if step == "chat" else "model_health_summary"
    routed = asyncio.run(advise(AdviceRequest(operation=operation, context=rules.brief(ctx, detail=step == "chat"), question=question), _ai_settings()))
    if routed.draft is None:
        message = _ai_off_message(routed.reason)
    else:
        message = AssistantMessage(role="assistant", text=routed.draft.text, model=routed.draft.model)
    return AssistantStepResult(step=step, title=_TITLES[step], messages=[message])  # type: ignore[arg-type]


@router.post(
    "/projects/{project_id}/workspace/assistant/{step}",
    response_model=AssistantStepResult,
)
def run_step(
    project_id: UUID,
    step: str,
    body: AssistantStepRequest,
    session: Session = Depends(get_session),
    store: ArtifactStore = Depends(get_artifact_store),
) -> AssistantStepResult:
    _power_bi_only(session, project_id)
    ctx = _context(session, project_id, store)
    items = body.items
    if step == "inventory":
        result = rules.inventory(ctx)
    elif step == "check_references":
        result = rules.check_references(ctx, items)
    elif step == "check_mquery":
        result = rules.check_mquery(ctx, items)
    elif step == "format_mquery":
        result = rules.format_mquery(ctx, items)
    elif step == "model_health":
        result = rules.model_health(ctx)
    elif step == "draft_dax":
        result = _draft_dax(session, project_id, ctx, items)
    elif step == "summarize":
        result = _advice("summarize", ctx)
    elif step == "chat":
        if not body.message.strip():
            raise ApiException(
                ErrorCategory.VALIDATION_ERROR,
                "Type a question for the assistant first.",
                detail="chat with an empty message",
                status_code=400,
            )
        result = _advice("chat", ctx, body.message.strip())
    else:
        raise ApiException(
            ErrorCategory.NOT_FOUND,
            f"There is no assistant step called {step}.",
            detail=f"unknown assistant step {step!r}",
            status_code=404,
        )
    logger.info(
        "assistant step",
        extra={"project_id": str(project_id), "operation": f"assistant.{step}"},
    )
    return result
