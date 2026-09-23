"""The review loop (`P4.6`, ADR-007): a model proposes, a person decides.

The rule the whole feature exists to keep is that **nothing auto-applies**.
There is no code path from "the model answered" to "the model's answer is in the
output"; accepting is a separate request a person makes, and until they make it
the proposal changes nothing.

The second rule is that every "no" keeps its name. An item without a proposal
says whether the model was never asked, was asked and declined, or answered and
had its answer discarded by the gauntlet. Only the third says anything about the
answer's quality, and merging them into "no suggestion available" throws away the
only part a person could act on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PREFIX = "/api/v1"


def _converted(client) -> str:
    project_id = client.post(
        f"{PREFIX}/projects",
        json={
            "source_platform": "tableau",
            "target_platform": "powerbi",
            "name": "Proposals",
        },
    ).json()["project_id"]
    client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={
            "file": (
                "clashes.twb",
                (FIXTURES / "clashes.twb").read_bytes(),
                "application/octet-stream",
            )
        },
    )
    client.post(f"{PREFIX}/projects/{project_id}/analysis")
    started = client.post(
        f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False}
    )
    assert started.status_code == 202, started.text
    return project_id


def _with_a_model(monkeypatch, answer: dict) -> None:
    """Point the router at a mock that returns exactly `answer`.

    The mock is a first-class provider (07-ai-engine.md), which is what lets the
    whole loop - route, prompt, gauntlet, store, decide - be exercised with no
    runtime anywhere and no flake.
    """
    from engines.ai import MockProvider

    import app.api.proposals as module

    real_route = module.route

    async def routed(request, settings, provider=None):
        return await real_route(
            request, settings, provider=MockProvider(answer=json.dumps(answer))
        )

    monkeypatch.setattr(module, "route", routed)
    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setenv("PRIVACY_MODE", "local_only")
    from app.core.config import settings

    settings.cache_clear()


def _good_answer(target: str = "SUM('Returns'[Return Count])") -> dict:
    return {
        "operation": "translate_calculation",
        "source_expression": "[Quantity] * 1.0",
        "target_expression": target,
        "explanation": "Reads the underlying count instead of the table calc.",
        "confidence": 0.9,
        "assumptions": ["The running total is not needed downstream."],
        "requires_review": True,
    }


# --- before a model is anywhere near it -------------------------------------


def test_proposals_before_a_conversion_are_refused_in_the_users_terms(api):
    project_id = api.client.post(
        f"{PREFIX}/projects",
        json={"source_platform": "tableau", "target_platform": "powerbi", "name": "x"},
    ).json()["project_id"]

    response = api.client.post(f"{PREFIX}/projects/{project_id}/proposals")

    assert response.status_code == 409
    assert "convert" in response.json()["message"].lower()


def test_with_no_provider_nothing_is_sent_and_the_screen_is_told_why(api):
    """"Absent, not degraded", visible from the outside."""
    project_id = _converted(api.client)

    body = api.client.post(f"{PREFIX}/projects/{project_id}/proposals").json()

    assert body["reviews"] == []
    assert body["skipped"], "held items vanished instead of being accounted for"
    assert all(item["outcome"] == "not_enabled" for item in body["skipped"])
    assert "no model is configured" in body["summary"].lower()


# --- with a model ------------------------------------------------------------


def test_a_drafted_proposal_carries_what_was_sent_to_the_model(api, monkeypatch):
    """07-ai-engine.md: the reviewer sees what was sent.

    It is also the only way a person can check for themselves that the workbook
    was not sent - which is a claim they otherwise have to take on trust.
    """
    _with_a_model(monkeypatch, _good_answer())
    project_id = _converted(api.client)

    body = api.client.post(f"{PREFIX}/projects/{project_id}/proposals").json()

    assert body["reviews"], body["summary"]
    review = body["reviews"][0]
    assert "# SYSTEM INSTRUCTIONS" in review["prompt_sent"]
    assert "<<<USER-DATA " in review["prompt_sent"]
    assert review["refusal_reason"]
    assert review["decision"] == "pending"


def test_a_fresh_proposal_is_pending_and_nothing_says_otherwise(api, monkeypatch):
    _with_a_model(monkeypatch, _good_answer())
    project_id = _converted(api.client)

    body = api.client.post(f"{PREFIX}/projects/{project_id}/proposals").json()

    for review in body["reviews"]:
        assert review["decision"] == "pending"
        assert review["proposal"]["requires_review"] is True
    assert "has been applied" in body["summary"].lower()


def test_an_answer_the_gauntlet_discards_is_reported_as_such(api, monkeypatch):
    """Not as "the model had nothing to say" - it said something unusable."""
    _with_a_model(monkeypatch, _good_answer(target="SUM(Nowhere[Nothing])"))
    project_id = _converted(api.client)

    body = api.client.post(f"{PREFIX}/projects/{project_id}/proposals").json()

    assert body["reviews"] == []
    assert any(item["outcome"] == "unknown_reference" for item in body["skipped"])


# --- the decision ------------------------------------------------------------


def test_accepting_is_a_separate_act_and_the_only_way_it_happens(api, monkeypatch):
    _with_a_model(monkeypatch, _good_answer())
    project_id = _converted(api.client)
    created = api.client.post(f"{PREFIX}/projects/{project_id}/proposals").json()
    proposal_id = created["reviews"][0]["proposal"]["proposal_id"]

    before = api.client.get(f"{PREFIX}/projects/{project_id}/proposals").json()
    assert all(r["decision"] == "pending" for r in before["reviews"])

    accepted = api.client.post(
        f"{PREFIX}/projects/{project_id}/proposals/{proposal_id}/accepted"
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["decision"] == "accepted"

    after = api.client.get(f"{PREFIX}/projects/{project_id}/proposals").json()
    assert [r["decision"] for r in after["reviews"]].count("accepted") == 1


def test_a_rejected_proposal_is_kept_not_deleted(api, monkeypatch):
    """§62 wants accepted, rejected and pending separable after the fact.

    Deleting the rejected ones would quietly improve the accuracy metrics.
    """
    _with_a_model(monkeypatch, _good_answer())
    project_id = _converted(api.client)
    created = api.client.post(f"{PREFIX}/projects/{project_id}/proposals").json()
    proposal_id = created["reviews"][0]["proposal"]["proposal_id"]

    api.client.post(f"{PREFIX}/projects/{project_id}/proposals/{proposal_id}/rejected")

    after = api.client.get(f"{PREFIX}/projects/{project_id}/proposals").json()
    assert any(r["decision"] == "rejected" for r in after["reviews"])


def test_a_decision_cannot_be_moved_back_to_not_looked_at(api, monkeypatch):
    _with_a_model(monkeypatch, _good_answer())
    project_id = _converted(api.client)
    created = api.client.post(f"{PREFIX}/projects/{project_id}/proposals").json()
    proposal_id = created["reviews"][0]["proposal"]["proposal_id"]

    response = api.client.post(
        f"{PREFIX}/projects/{project_id}/proposals/{proposal_id}/pending"
    )
    assert response.status_code == 400


def test_re_running_does_not_resurrect_a_rejected_proposal(api, monkeypatch):
    """The failure that would matter: a reviewer's "no" quietly undone.

    Proposal ids are deterministic over the two expressions, so the same draft
    for the same expression is the same row and its decision stands.
    """
    _with_a_model(monkeypatch, _good_answer())
    project_id = _converted(api.client)
    created = api.client.post(f"{PREFIX}/projects/{project_id}/proposals").json()
    proposal_id = created["reviews"][0]["proposal"]["proposal_id"]
    api.client.post(f"{PREFIX}/projects/{project_id}/proposals/{proposal_id}/rejected")

    again = api.client.post(f"{PREFIX}/projects/{project_id}/proposals").json()

    decided = {r["proposal"]["proposal_id"]: r["decision"] for r in again["reviews"]}
    assert decided[proposal_id] == "rejected"


def test_a_get_never_asks_a_model_again(api, monkeypatch):
    """A GET that quietly cost money and returned different text is a GET in
    name only."""
    _with_a_model(monkeypatch, _good_answer())
    project_id = _converted(api.client)
    api.client.post(f"{PREFIX}/projects/{project_id}/proposals")

    first = api.client.get(f"{PREFIX}/projects/{project_id}/proposals").json()
    second = api.client.get(f"{PREFIX}/projects/{project_id}/proposals").json()

    assert first["reviews"] == second["reviews"]


def test_only_accepted_proposals_are_offered_to_a_re_conversion(api, monkeypatch):
    """The storage layer must not become the auto-apply path."""
    _with_a_model(monkeypatch, _good_answer())
    project_id = _converted(api.client)
    created = api.client.post(f"{PREFIX}/projects/{project_id}/proposals").json()
    proposal_id = created["reviews"][0]["proposal"]["proposal_id"]

    api.client.post(f"{PREFIX}/projects/{project_id}/proposals/{proposal_id}/rejected")
    assert _accepted(api, project_id) == {}

    api.client.post(f"{PREFIX}/projects/{project_id}/proposals/{proposal_id}/accepted")
    assert list(_accepted(api, project_id)) == [created["reviews"][0]["item"]]


def _accepted(api, project_id: str) -> dict:
    """`accepted_dax` against the same database the client is using."""
    from uuid import UUID

    from app.api.proposals import accepted_dax
    from app.core.db import get_session

    generator = api.client.app.dependency_overrides[get_session]()
    session = next(generator)
    try:
        return accepted_dax(session, UUID(project_id))
    finally:
        generator.close()


@pytest.mark.parametrize("decision", ["accepted", "rejected"])
def test_deciding_on_a_proposal_that_is_not_there_is_a_404(api, decision):
    project_id = _converted(api.client)
    missing = "11111111-1111-1111-1111-111111111111"
    response = api.client.post(
        f"{PREFIX}/projects/{project_id}/proposals/{missing}/{decision}"
    )
    assert response.status_code == 404


# --- the loop closing --------------------------------------------------------


def test_accepting_changes_the_next_conversion_and_says_who_wrote_it(api, monkeypatch):
    """The other half of ADR-007: a person's decision has to actually do
    something, and the output has to say a model drafted it.

    Without the second part an accepted draft is indistinguishable from a rule's
    output in the produced model, and §62 - what did the AI actually contribute?
    - has no answer.
    """
    _with_a_model(monkeypatch, _good_answer())
    project_id = _converted(api.client)
    created = api.client.post(f"{PREFIX}/projects/{project_id}/proposals").json()
    review = created["reviews"][0]
    item = review["item"]

    before = api.client.get(f"{PREFIX}/projects/{project_id}/conversion").json()
    assert _translation(before, item) is None, "it was refused, so it has no target"

    api.client.post(
        f"{PREFIX}/projects/{project_id}/proposals/{review['proposal']['proposal_id']}/accepted"
    )
    again = api.client.post(
        f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False}
    )
    assert again.status_code == 202, again.text

    after = api.client.get(f"{PREFIX}/projects/{project_id}/conversion").json()
    translation = _translation(after, item)
    assert translation is not None, "the accepted expression was not used"
    assert translation["target_text"] == review["proposal"]["target_expression"]
    assert translation["method"] == "ai_assisted"
    assert translation["proposal_id"] == review["proposal"]["proposal_id"]
    assert translation["rule_ids"] == [], "no rule produced this"


def test_a_pending_proposal_changes_nothing(api, monkeypatch):
    """The auto-apply path, checked for at the place it would appear."""
    _with_a_model(monkeypatch, _good_answer())
    project_id = _converted(api.client)
    created = api.client.post(f"{PREFIX}/projects/{project_id}/proposals").json()
    item = created["reviews"][0]["item"]

    api.client.post(f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False})

    after = api.client.get(f"{PREFIX}/projects/{project_id}/conversion").json()
    assert _translation(after, item) is None, (
        "a proposal nobody accepted reached the output"
    )


def test_the_report_says_a_model_contributed(api, monkeypatch):
    """§62, in the document that outlives the session."""
    _with_a_model(monkeypatch, _good_answer())
    project_id = _converted(api.client)
    created = api.client.post(f"{PREFIX}/projects/{project_id}/proposals").json()
    api.client.post(
        f"{PREFIX}/projects/{project_id}/proposals/"
        f"{created['reviews'][0]['proposal']['proposal_id']}/accepted"
    )
    api.client.post(f"{PREFIX}/projects/{project_id}/conversion", json={"ai_enabled": False})

    html = api.client.get(f"{PREFIX}/projects/{project_id}/report?format=html").text
    assert "AI-assisted" in html
    assert "no provider was configured" not in html


def _translation(conversion: dict, item: str):
    for datasource in conversion["model"]["datasources"]:
        for table in datasource["tables"]:
            for column in table["columns"]:
                if column["id"] == item:
                    return column.get("translation")
    return None
