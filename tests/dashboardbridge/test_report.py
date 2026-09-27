"""The conversion report: the deliverable a person keeps after the run.

The report outlives the session. It is the artefact that gets attached to a
ticket, mailed to a lead, and read by someone who never saw the screen it came
from — so the rules the results screen enforces have to hold here too, without
the screen's help.

Three of them are load-bearing and are what most of these tests protect:

* **What did not convert is as much a result as what did** (03-ux-spec.md). A
  report listing only successes is a sales document.
* **No claim without evidence.** A report produced before validation ran says
  so; it does not quietly omit the section, because an omitted verdict reads as
  a passed one.
* **Names in it come from an untrusted file.** A Tableau field can be called
  anything at all, including markup. The HTML rendering has to survive that.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.support.engines import needs_tableau

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PREFIX = "/api/v1"


def _project(client, name: str = "Report test") -> str:
    return client.post(
        f"{PREFIX}/projects",
        json={
            "source_platform": "tableau",
            "target_platform": "powerbi",
            "name": name,
        },
    ).json()["project_id"]


def _converted(client, name: str = "Report test") -> str:
    """A project taken all the way through conversion, but not validated."""
    project_id = _project(client, name)
    client.post(
        f"{PREFIX}/projects/{project_id}/artifacts",
        files={
            "file": (
                "sample.twb",
                (FIXTURES / "sample.twb").read_bytes(),
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


def _report_of(client, project_id: str):
    """The report as the contract, so a test can do arithmetic on it."""
    from dashboardbridge_contracts import ConversionReport

    body = client.get(f"{PREFIX}/projects/{project_id}/report?format=json").json()
    return ConversionReport.model_validate(body)


@pytest.fixture
def validated(api):
    project_id = _converted(api.client)
    api.client.post(f"{PREFIX}/projects/{project_id}/validation")
    return project_id


# --- when there is nothing to report --------------------------------------


@needs_tableau
def test_a_report_before_conversion_is_refused_in_the_users_terms(api):
    project_id = _project(api.client)
    response = api.client.get(f"{PREFIX}/projects/{project_id}/report")
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["category"] == "CONVERSION_ERROR"
    assert "Traceback" not in body["message"]


@needs_tableau
def test_an_unknown_format_is_refused_rather_than_guessed_at(api, validated):
    response = api.client.get(f"{PREFIX}/projects/{validated}/report?format=pdf")
    assert response.status_code in {400, 422}


# --- the JSON report -------------------------------------------------------


@needs_tableau
def test_json_is_the_default_format(api, validated):
    response = api.client.get(f"{PREFIX}/projects/{validated}/report")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")


@needs_tableau
def test_the_report_carries_every_flag_with_all_three_axes(api, validated):
    body = api.client.get(f"{PREFIX}/projects/{validated}/report?format=json").json()
    assert body["flags"], "a report with no flags hides the work that remains"
    for flag in body["flags"]:
        assert flag["method"] and flag["status"] and flag["severity"]
        assert flag["reason"]


@needs_tableau
def test_the_report_carries_the_counts_and_they_sum_to_the_whole(api, validated):
    body = api.client.get(f"{PREFIX}/projects/{validated}/report?format=json").json()
    c = body["compatibility"]
    assert (
        c["converted"] + c["partial"] + c["ai_required"] + c["unsupported"] + c["failed"]
        == c["total"]
    )


@needs_tableau
def test_the_report_carries_the_validation_verdict_when_one_exists(api, validated):
    body = api.client.get(f"{PREFIX}/projects/{validated}/report?format=json").json()
    assert body["validation"] is not None
    assert body["validation"]["verdict"] in {
        "verified",
        "partially_verified",
        "unverified",
        "failed",
    }
    assert body["validation"]["rules"]


@needs_tableau
def test_an_unvalidated_conversion_reports_unverified_rather_than_silence(api):
    """The absence has to be stated. An omitted verdict reads as a passed one."""
    project_id = _converted(api.client)
    body = api.client.get(f"{PREFIX}/projects/{project_id}/report?format=json").json()
    assert body["validation"] is None
    assert body["verdict"] == "unverified"


@needs_tableau
def test_the_report_names_the_workbook_it_describes(api):
    project_id = _converted(api.client, name="Quarterly numbers.twb")
    body = api.client.get(f"{PREFIX}/projects/{project_id}/report?format=json").json()
    assert body["project"]["name"] == "Quarterly numbers.twb"


@needs_tableau
def test_two_reports_of_the_same_run_are_identical(api, validated):
    """A report that changes between reads cannot be attached to a ticket."""
    first = api.client.get(f"{PREFIX}/projects/{validated}/report?format=json").text
    second = api.client.get(f"{PREFIX}/projects/{validated}/report?format=json").text
    assert first == second


# --- the HTML report -------------------------------------------------------


@needs_tableau
def test_html_is_served_as_html(api, validated):
    response = api.client.get(f"{PREFIX}/projects/{validated}/report?format=html")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")


@needs_tableau
def test_the_html_report_fetches_nothing_from_the_internet(api, validated):
    """Offline is the product's promise, and a report is where it leaks.

    One remote stylesheet or font turns a document someone opens on an
    air-gapped machine into a request to a third party that records who read it
    and when (ADR-006, §51).
    """
    html = api.client.get(f"{PREFIX}/projects/{validated}/report?format=html").text
    for marker in ("http://", "https://", "//fonts.", "<script src"):
        assert marker not in html, f"the report reaches out via {marker!r}"


@needs_tableau
def test_the_html_report_states_what_did_not_convert(api, validated):
    html = api.client.get(f"{PREFIX}/projects/{validated}/report?format=html").text
    # The sample workbook refuses RUNNING_SUM; that refusal is the report's
    # most useful sentence and must survive into the rendering.
    assert "Running Total" in html


@needs_tableau
def test_the_html_report_shows_the_verdict_word(api, validated):
    html = api.client.get(f"{PREFIX}/projects/{validated}/report?format=html").text
    assert any(
        word in html
        for word in ("Verified", "Partially verified", "Unverified", "Failed")
    )


@needs_tableau
def test_the_html_report_never_prints_a_bare_percentage(api, validated):
    """A percentage is the number people quote and cannot defend.

    Measured on what a reader actually sees, not on the source: a stylesheet is
    full of legitimate percentages and none of them is a claim about the
    conversion.
    """
    html = api.client.get(f"{PREFIX}/projects/{validated}/report?format=html").text
    visible = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    visible = re.sub(r"<[^>]+>", " ", visible)
    assert "%" not in visible


@needs_tableau
def test_a_name_from_the_workbook_cannot_become_markup(api):
    """Every name in this document came out of a file we did not write.

    A Tableau workbook can name a field anything, and a project can be named
    after it. Rendering that into HTML unescaped is a stored cross-site
    scripting hole in a document people are told to open and forward.
    """
    hostile = '<script>alert("xss")</script>'
    project_id = _converted(api.client, name=hostile)
    html = api.client.get(f"{PREFIX}/projects/{project_id}/report?format=html").text
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


@needs_tableau
def test_two_html_reports_of_the_same_run_are_identical(api, validated):
    first = api.client.get(f"{PREFIX}/projects/{validated}/report?format=html").text
    second = api.client.get(f"{PREFIX}/projects/{validated}/report?format=html").text
    assert first == second


# --- the executive summary (P5.6) -----------------------------------------


@needs_tableau
def test_the_means_of_conversion_sum_to_the_denominator(api, validated):
    """"How was this converted" must survive the same arithmetic as "how much".

    A breakdown by means that does not account for every object counted is a
    selection, and a selection is the thing this report exists not to be. The
    parts are derived so they cannot drift: everything unflagged came across by
    rule, and every flag names the means that handled it.
    """
    from app.services.report import means_of_conversion

    report = _report_of(api.client, validated)
    means = means_of_conversion(report)
    assert (
        means.by_rule + means.ai_assisted + means.by_hand
        == report.compatibility.total
    )


@needs_tableau
def test_the_means_are_taken_from_the_flags_not_assumed_from_the_status(api, validated):
    """Method and status are different axes (ADR-004) and are read as such."""
    from app.services.report import means_of_conversion

    report = _report_of(api.client, validated)
    means = means_of_conversion(report)
    by_hand = sum(
        1
        for flag in report.flags
        if flag.method.value == "manual" and flag.status.value != "converted"
    )
    assert means.by_hand == by_hand


@needs_tableau
def test_the_html_report_says_by_what_means_the_objects_came_across(api, validated):
    html = api.client.get(f"{PREFIX}/projects/{validated}/report?format=html").text
    assert "How it was converted" in html
    assert "By rule" in html
    assert "By hand" in html


@needs_tableau
def test_no_ai_reports_its_absence_rather_than_a_bare_zero(api, validated):
    """A bare "AI-assisted 0" reads as "the model tried and produced nothing".

    No provider is configured, so nothing was attempted. The report says which
    of the two happened, because they are different facts about the run.
    """
    html = api.client.get(f"{PREFIX}/projects/{validated}/report?format=html").text
    assert "no provider was configured" in html.lower()


# --- key risks (P5.6) ------------------------------------------------------


def _risk_report(reasons: list[tuple[str, int]], converted_note: str = ""):
    """A report carrying exactly the flags a test wants to reason about."""
    from dashboardbridge_contracts import (
        Compatibility,
        ConversionFlag,
        ConversionReport,
        Project,
    )

    flags = [
        ConversionFlag(
            item=f"{reason[:8]}-{index}",
            stage="map",
            method="manual",
            status="unsupported",
            severity="manual",
            reason=reason,
            ref=f"{reason[:8]}-{index}",
        )
        for reason, count in reasons
        for index in range(count)
    ]
    if converted_note:
        flags.append(
            ConversionFlag(
                item="fine",
                stage="map",
                method="deterministic",
                status="converted",
                severity="info",
                reason=converted_note,
                ref="fine",
            )
        )
    return ConversionReport(
        project=Project(
            project_id="00000000-0000-0000-0000-000000000001",
            source_platform="tableau",
            target_platform="powerbi",
            name="Risks",
            created_at="2026-01-01T00:00:00Z",
        ),
        compatibility=Compatibility(total=len(flags)),
        flags=flags,
    )


def test_key_risks_lead_with_what_affects_the_most_objects():
    from app.services.report import key_risks

    risks, _ = key_risks(_risk_report([("rare", 2), ("common", 9), ("some", 5)]))
    assert [risk.count for risk in risks] == [9, 5, 2]
    assert risks[0].sentence == "common"


def test_key_risks_say_how_many_objects_they_left_out():
    """A shortened list that does not admit it is shortened reads as complete."""
    from app.services.report import key_risks

    reasons = [(f"reason {index}", index + 1) for index in range(8)]
    risks, omitted = key_risks(_risk_report(reasons), limit=3)
    assert len(risks) == 3
    assert omitted == sum(count for _, count in reasons) - sum(r.count for r in risks)
    assert omitted > 0


def test_a_note_about_something_that_converted_is_not_a_risk():
    from app.services.report import key_risks

    risks, omitted = key_risks(
        _risk_report([("held", 3)], converted_note="Converted cleanly.")
    )
    assert [risk.sentence for risk in risks] == ["held"]
    assert omitted == 0


def test_two_risks_of_the_same_size_are_always_ordered_the_same_way():
    from app.services.report import key_risks

    forward, _ = key_risks(_risk_report([("beta", 4), ("alpha", 4)]))
    backward, _ = key_risks(_risk_report([("alpha", 4), ("beta", 4)]))
    assert [r.sentence for r in forward] == [r.sentence for r in backward]


def test_a_conversion_with_nothing_held_reports_no_risks():
    from app.services.report import key_risks

    risks, omitted = key_risks(_risk_report([]))
    assert risks == []
    assert omitted == 0


@needs_tableau
def test_the_html_report_leads_with_the_key_risks(api, validated):
    html = api.client.get(f"{PREFIX}/projects/{validated}/report?format=html").text
    assert "Key risks" in html
    # Before the full list, because a summary a reader reaches after the detail
    # is not a summary.
    assert html.index("Key risks") < html.index("What did not come across")


def test_a_hostile_reason_cannot_become_markup_in_the_risks_section():
    from app.services.report import render_html

    html = render_html(_risk_report([('<img src=x onerror="alert(1)">', 2)]))
    assert "<img src=x" not in html
    assert "&lt;img" in html


# --- the audit trail (P5.7) ------------------------------------------------


@needs_tableau
def test_the_report_carries_an_entry_for_every_object_the_run_handled(api, validated):
    body = api.client.get(f"{PREFIX}/projects/{validated}/report?format=json").json()
    assert body["audit"], "a report with no audit trail cannot defend anything"
    for entry in body["audit"]:
        assert entry["stage"] and entry["kind"] and entry["name"]
        assert entry["outcome"] in {"crossed", "held"}


@needs_tableau
def test_the_audit_trail_records_what_crossed_not_only_what_did_not(api, validated):
    """The flags say what failed. Only this says what succeeded, and how.

    "A migration architect can defend every transformation" (01-product-spec)
    is a claim about the conversions that worked. A document that lists only
    refusals cannot support it.
    """
    body = api.client.get(f"{PREFIX}/projects/{validated}/report?format=json").json()
    crossed = [e for e in body["audit"] if e["outcome"] == "crossed"]
    assert crossed, "nothing recorded as having come across"


@needs_tableau
def test_a_translated_calculation_carries_both_expressions(api, validated):
    """Source beside result, on the record, is what makes it auditable."""
    body = api.client.get(f"{PREFIX}/projects/{validated}/report?format=json").json()
    calcs = [
        e
        for e in body["audit"]
        if e["kind"] == "calc" and e["outcome"] == "crossed" and e["result"]
    ]
    assert calcs, "no translated calculation was recorded with its DAX"
    assert all(entry["source"] for entry in calcs)


@needs_tableau
def test_the_audit_trail_carries_no_timing(api, validated):
    """Determinism outranks forensic detail here.

    The report must be byte-stable: two runs of the same workbook produce the
    same document, or it cannot be diffed, attached, or trusted as a record.
    An elapsed time is different on every run, so it stays in the event stream,
    where it is about a run in progress rather than a record of one.
    """
    body = api.client.get(f"{PREFIX}/projects/{validated}/report?format=json").json()
    for entry in body["audit"]:
        assert not any("elapsed" in key or "ms" == key[-2:] for key in entry)


def test_a_conversion_with_no_recording_reports_its_absence(api):
    """An empty section is not the same as a missing one."""
    from app.services.report import render_html

    html = render_html(_risk_report([("held", 1)]))
    assert "Audit trail" in html
    assert "no recording" in html.lower()


@needs_tableau
def test_the_html_report_shows_the_audit_trail(api, validated):
    html = api.client.get(f"{PREFIX}/projects/{validated}/report?format=html").text
    assert "Audit trail" in html
    assert "Came across" in html


@needs_tableau
def test_the_audit_trail_names_the_stage_that_did_the_work(api, validated):
    """A stage every entry shares is a stage nobody recorded.

    The engine names its stages "Parse", "Translate", "Map"; the contract's are
    lower case. A lookup that misses relabels every entry to one fallback value,
    which still renders, still validates, and is wrong on every row.
    """
    body = api.client.get(f"{PREFIX}/projects/{validated}/report?format=json").json()
    stages = {entry["stage"] for entry in body["audit"]}
    assert len(stages) > 1, f"every entry claims one stage: {stages}"

    calcs = [e for e in body["audit"] if e["kind"] == "calc"]
    assert calcs, "the fixture has no calculation to place"
    assert {entry["stage"] for entry in calcs} == {"translate"}
