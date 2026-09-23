"""Ask a model about what the converter refused, and record what a person says.

`P4.6`, ADR-007. Two rules shape every line here:

**Nothing auto-applies.** A proposal is produced, stored and shown. It changes
nothing until a person accepts it, and accepting is a separate request that a
person makes. There is no code path from "the model answered" to "the model's
answer is in the output".

**Every "no" keeps its name.** An item with no proposal carries the reason it
has none - the model was never asked, or was asked and declined, or answered and
the gauntlet discarded it. Those are three different facts and only the last one
says anything about the answer's quality.

Running is inline, like analysis and conversion, and produces no job row: it
writes nothing to the artifact store, changes no output, and re-running it is
free. What it *does* write is the proposals themselves, because a decision has
to have something durable to attach to.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from dashboardbridge_contracts import (
    Conversion,
    ProposalReview,
    ProposalSet,
    SkippedItem,
)
from dashboardbridge_contracts.enums import ErrorCategory, ProposalDecision, ProviderKind
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.queries import latest_job as _latest
from app.api.projects import load_project
from app.api.settings import _ai_settings
from app.core.config import settings
from app.core.db import get_session
from app.core.errors import ApiException
from app.db.models import JobKind as DbJobKind
from app.db.models import Proposal as ProposalRow
from engines.ai.prompts import load_prompt, render
from engines.ai.proposal import vet
from engines.ai.router import Disposition, route
from engines.conversion.ai_requests import policy_for, request_for

logger = logging.getLogger(__name__)
router = APIRouter(tags=["proposals"])


def _conversion(session: Session, project_id: UUID) -> Conversion:
    job = _latest(session, project_id, DbJobKind.CONVERSION)
    if job is None or job.result is None:
        raise ApiException(
            ErrorCategory.CONVERSION_ERROR,
            "Convert the workbook first. There is nothing to ask a model about "
            "until the deterministic converter has said what it could not do.",
            detail=f"no completed conversion for project {project_id}",
            status_code=409,
        )
    return Conversion.model_validate(job.result)


def _refused(conversion: Conversion) -> list[tuple[str, str]]:
    """`(column id, why it was refused)` for every calculation held back.

    Only expressions. A worksheet filter or a dashboard layout also needs a
    person, but it needs one to *rebuild* it, which is not something a model can
    draft - the same distinction `_status` makes in the conversion outcome.
    """
    reasons = {flag.ref or flag.item: flag.reason for flag in conversion.flags}
    held: list[tuple[str, str]] = []
    for datasource in (conversion.model.datasources if conversion.model else []) or []:
        for table in datasource.tables or []:
            for column in table.columns or []:
                if column.expression and not column.translation:
                    held.append((column.id, reasons.get(column.id, "Not converted.")))
    return held


@router.post("/projects/{project_id}/proposals", response_model=ProposalSet)
def create_proposals(
    project_id: UUID, session: Session = Depends(get_session)
) -> ProposalSet:
    load_project(session, project_id)
    conversion = _conversion(session, project_id)
    held = _refused(conversion)

    if conversion.model is None:
        raise ApiException(
            ErrorCategory.CONVERSION_ERROR,
            "The conversion did not return its model, so there is nothing to "
            "describe to a model.",
            detail=f"conversion for {project_id} carries no model",
            status_code=409,
        )

    ai = _ai_settings()
    policy = policy_for(conversion.model)
    reviews: list[ProposalReview] = []
    skipped: list[SkippedItem] = []

    for item, reason in held:
        request = request_for(conversion.model, item, reason)
        routed = asyncio.run(route(request, ai))

        if routed.draft is None:
            skipped.append(
                SkippedItem(item=item, outcome=routed.disposition.value, reason=routed.reason)
            )
            continue

        verdict = vet(
            routed.draft.text,
            request,
            policy,
            model=routed.draft.model,
            prompt_version=routed.draft.prompt_version,
        )
        if verdict.proposal is None:
            # The gauntlet discarded it. Reported as such: "the model answered
            # and the answer did not survive checking" is a fact about the
            # answer, not about whether a model was reachable.
            skipped.append(
                SkippedItem(
                    item=item,
                    outcome=(verdict.rejection.value if verdict.rejection else "discarded"),
                    reason=verdict.reason,
                )
            )
            continue

        reviews.append(
            ProposalReview(
                item=item,
                refusal_reason=reason,
                proposal=verdict.proposal,
                prompt_sent=render(load_prompt(request.operation), request),
                decision=ProposalDecision.PENDING,
            )
        )

    _store(session, project_id, reviews)
    session.commit()

    logger.info(
        "proposals produced",
        extra={
            "project_id": str(project_id),
            "operation": "proposals",
        },
    )
    return ProposalSet(
        project_id=project_id,
        reviews=_merge_decisions(session, project_id, reviews),
        skipped=skipped,
        summary=_summary(len(held), len(reviews), len(skipped), ai.provider),
    )


def _summary(held: int, drafted: int, skipped: int, provider: ProviderKind) -> str:
    """Said even when nothing was produced.

    An empty list with no sentence beside it reads as "the model had nothing to
    say", which is only one of the reasons it could be empty.
    """
    if provider is ProviderKind.NONE:
        return (
            f"{held} held item(s). No model is configured, so none of them was "
            "sent anywhere and nothing was drafted."
        )
    return (
        f"{held} held item(s): {drafted} drafted for your review, {skipped} not. "
        "Nothing here has been applied."
    )


def _store(session: Session, project_id: UUID, reviews: list[ProposalReview]) -> None:
    """Write proposals, without disturbing decisions already made.

    A re-run must not resurrect something a person rejected: proposal ids are
    deterministic over the two expressions, so the same draft for the same
    expression is the same row, and its decision stands.
    """
    existing = {
        row.proposal_id
        for row in session.scalars(
            select(ProposalRow).where(ProposalRow.project_id == project_id)
        )
    }
    for review in reviews:
        if review.proposal.proposal_id in existing:
            continue
        session.add(
            ProposalRow(
                proposal_id=review.proposal.proposal_id,
                project_id=project_id,
                item=review.item,
                review=review.model_dump(mode="json"),
                decision=ProposalDecision.PENDING.value,
            )
        )


def _merge_decisions(
    session: Session, project_id: UUID, reviews: list[ProposalReview]
) -> list[ProposalReview]:
    decided = {
        row.proposal_id: row.decision
        for row in session.scalars(
            select(ProposalRow).where(ProposalRow.project_id == project_id)
        )
    }
    return [
        review.model_copy(
            update={
                "decision": ProposalDecision(
                    decided.get(review.proposal.proposal_id, ProposalDecision.PENDING.value)
                )
            }
        )
        for review in reviews
    ]


@router.get("/projects/{project_id}/proposals", response_model=ProposalSet)
def get_proposals(
    project_id: UUID, session: Session = Depends(get_session)
) -> ProposalSet:
    """What was drafted before, with the decisions as they stand.

    Never re-asks a model: a GET that quietly cost money and produced different
    text would be a GET in name only.
    """
    load_project(session, project_id)
    rows = list(
        session.scalars(
            select(ProposalRow)
            .where(ProposalRow.project_id == project_id)
            .order_by(ProposalRow.item)
        )
    )
    reviews = [
        ProposalReview.model_validate(row.review).model_copy(
            update={"decision": ProposalDecision(row.decision)}
        )
        for row in rows
    ]
    return ProposalSet(
        project_id=project_id,
        reviews=reviews,
        summary=(
            f"{len(reviews)} proposal(s) on record. "
            f"{sum(1 for r in reviews if r.decision is ProposalDecision.ACCEPTED)} "
            "accepted. Accepting one records your decision; it does not change "
            "anything already produced until the workbook is converted again."
        ),
    )


@router.post(
    "/projects/{project_id}/proposals/{proposal_id}/{decision}",
    response_model=ProposalReview,
)
def decide(
    project_id: UUID,
    proposal_id: UUID,
    decision: ProposalDecision,
    session: Session = Depends(get_session),
) -> ProposalReview:
    """Record a person's decision. The only way a proposal ever becomes accepted.

    `pending` is refused: it is the state a proposal starts in, not a decision
    anyone makes, and allowing it would let a caller quietly un-review something.
    """
    load_project(session, project_id)
    if decision is ProposalDecision.PENDING:
        raise ApiException(
            ErrorCategory.VALIDATION_ERROR,
            "A proposal can be accepted or rejected. It cannot be moved back to "
            "not-yet-looked-at.",
            detail="pending is a starting state, not a decision",
            status_code=400,
        )

    row = session.scalars(
        select(ProposalRow).where(
            ProposalRow.project_id == project_id,
            ProposalRow.proposal_id == proposal_id,
        )
    ).first()
    if row is None:
        raise ApiException(
            ErrorCategory.NOT_FOUND,
            "That proposal is not on record for this project.",
            detail=f"no proposal {proposal_id} for project {project_id}",
            status_code=404,
        )

    row.decision = decision.value
    session.commit()
    return ProposalReview.model_validate(row.review).model_copy(
        update={"decision": decision}
    )


def accepted_proposals(
    session: Session, project_id: UUID
) -> dict[str, tuple[str, str]]:
    """`{item: (expression, proposal id)}` for a re-conversion.

    The id travels with the expression so the produced model can say which
    proposal a translation came from, which is what §62 needs to separate AI
    contribution from deterministic work.
    """
    rows = session.scalars(
        select(ProposalRow).where(
            ProposalRow.project_id == project_id,
            ProposalRow.decision == ProposalDecision.ACCEPTED.value,
        )
    )
    return {
        row.item: (
            ProposalReview.model_validate(row.review).proposal.target_expression,
            str(row.proposal_id),
        )
        for row in rows
    }


def accepted_dax(session: Session, project_id: UUID) -> dict[str, str]:
    """Accepted proposals as `{item: expression}`, for a re-conversion.

    Only accepted ones. A pending proposal is a draft nobody has read, and a
    rejected one is a draft someone read and turned down; using either would be
    the auto-apply path ADR-007 rejects, arrived at from the storage layer.
    """
    rows = session.scalars(
        select(ProposalRow).where(
            ProposalRow.project_id == project_id,
            ProposalRow.decision == ProposalDecision.ACCEPTED.value,
        )
    )
    return {
        row.item: ProposalReview.model_validate(row.review).proposal.target_expression
        for row in rows
    }
