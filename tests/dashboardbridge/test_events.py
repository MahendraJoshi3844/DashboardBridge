"""The event stream. Real recorded work, never synthesised progress.

A percentage is `completed / total` of real items or it is not shown. The engine
records one event per item it handled; this endpoint carries that recording
across the boundary without inventing anything to smooth it.
"""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _converted(client) -> str:
    project_id = client.post(
        "/api/v1/projects",
        json={
            "source_platform": "tableau",
            "target_platform": "powerbi",
            "name": "Events test",
        },
    ).json()["project_id"]
    client.post(
        f"/api/v1/projects/{project_id}/artifacts",
        files={
            "file": (
                "sample.twb",
                (FIXTURES / "sample.twb").read_bytes(),
                "application/octet-stream",
            )
        },
    )
    client.post(f"/api/v1/projects/{project_id}/analysis")
    client.post(
        f"/api/v1/projects/{project_id}/conversion", json={"ai_enabled": False}
    )
    return project_id


def _events(response) -> list[dict]:
    """Parse an SSE body into its data payloads."""
    parsed = []
    for block in response.text.strip().split("\n\n"):
        payload = {}
        for line in block.splitlines():
            field, _, value = line.partition(":")
            payload[field.strip()] = value.strip()
        if "data" in payload:
            parsed.append({**payload, "data": json.loads(payload["data"])})
    return parsed


@pytest.fixture
def stream(api):
    project_id = _converted(api.client)
    response = api.client.get(f"/api/v1/projects/{project_id}/events")
    assert response.status_code == 200, response.text
    return project_id, response


def test_the_stream_is_server_sent_events(stream):
    _, response = stream
    assert response.headers["content-type"].startswith("text/event-stream")


def test_every_event_carries_the_item_it_describes(stream):
    _, response = stream
    items = [e for e in _events(response) if e.get("event") == "conversion.item"]
    assert items, "the recording should contain per-item events"
    for event in items:
        assert event["data"]["name"]
        assert event["data"]["outcome"] in {"crossed", "held"}


def test_progress_counts_real_items_never_a_synthesised_percentage(stream):
    _, response = stream
    progress = [e for e in _events(response) if e.get("event") == "conversion.progress"]
    assert progress
    for event in progress:
        assert event["data"]["completed"] <= event["data"]["total"]
    last = progress[-1]["data"]
    assert last["completed"] == last["total"], "the run finished; so must the count"


def test_the_stream_ends_by_saying_so(stream):
    _, response = stream
    assert _events(response)[-1]["event"] == "conversion.completed"


def test_events_carry_ids_so_a_dropped_connection_loses_nothing(stream):
    _, response = stream
    ids = [int(e["id"]) for e in _events(response) if "id" in e]
    assert ids == sorted(ids), "ids must be monotonic to resume from one"


def test_a_client_can_resume_from_where_it_stopped(api, stream):
    project_id, response = stream
    all_ids = [int(e["id"]) for e in _events(response) if "id" in e]
    midpoint = all_ids[len(all_ids) // 2]

    resumed = api.client.get(
        f"/api/v1/projects/{project_id}/events",
        headers={"last-event-id": str(midpoint)},
    )
    remaining = [int(e["id"]) for e in _events(resumed) if "id" in e]
    assert remaining, "resuming should replay what came after"
    assert min(remaining) > midpoint


def test_a_project_with_no_run_has_nothing_to_stream(api):
    project_id = api.client.post(
        "/api/v1/projects",
        json={
            "source_platform": "tableau",
            "target_platform": "powerbi",
            "name": "Nothing yet",
        },
    ).json()["project_id"]
    assert api.client.get(f"/api/v1/projects/{project_id}/events").status_code == 404
