"""Render a conversion report as a self-contained HTML document.

Pure: it takes a `ConversionReport` and returns a string. No clock, no request,
no database — which is what makes the output byte-stable, and a report that
changes between two reads is one nobody can attach to a ticket.

Three constraints shape everything below.

**It fetches nothing.** No stylesheet, font, script or image from anywhere. A
single remote reference turns a document opened on an air-gapped machine into a
request to a third party recording who read it and when (ADR-006, §51), and the
person forwarding it has no way to know. So the CSS is inline and the type is
whatever the reader already has.

**Every name in it came out of a file we did not write.** A Tableau field can be
called anything, including markup, and this document is meant to be opened and
forwarded. Everything interpolated goes through `escape()`; there is one
function that writes text into HTML and it is that one.

**No percentages.** Counts travel with their denominators. A percentage is the
number that gets quoted in a meeting and cannot be defended, and the whole point
of this document is that every figure in it can be.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from dashboardbridge_contracts import ConversionReport
from dashboardbridge_contracts.enums import ConversionMethod, Verdict


@dataclass(frozen=True)
class Means:
    """By what means the counted objects came across (P5.6).

    `status` answers what became of an object; this answers who or what did the
    work, which is the figure a lead is actually asking about when they ask how
    much of this was automated.
    """

    by_rule: int
    ai_assisted: int
    by_hand: int


def means_of_conversion(report: ConversionReport) -> Means:
    """Split the denominator by method, so the parts sum to it by construction.

    `by_rule` is derived by subtraction for the same reason `Compatibility`
    derives `converted` that way: an object with no flag came across by rule,
    and counting the two halves independently lets them drift apart until the
    breakdown quietly describes a different run from the one above it.

    Only flags that changed an outcome are counted. A `converted` flag is a
    note about an object that came across, and it is already inside the
    converted count - adding it here would count that object twice.
    """
    handled = [flag for flag in report.flags if flag.status.value != "converted"]
    # Counted whatever its status, unlike the others. An accepted draft *did*
    # convert, so it carries a `converted` flag - and excluding it would file
    # the one thing a model contributed under "by rule", which is precisely the
    # question §62 asks and precisely the wrong answer.
    ai_assisted = sum(
        1 for flag in report.flags if flag.method is ConversionMethod.AI_ASSISTED
    )
    by_hand = sum(1 for flag in handled if flag.method is ConversionMethod.MANUAL)
    return Means(
        by_rule=max(report.compatibility.total - ai_assisted - by_hand, 0),
        ai_assisted=ai_assisted,
        by_hand=by_hand,
    )

#: The four words and what each one is allowed to mean (§63). Kept beside the
#: renderer so the word and its meaning cannot drift apart, and deliberately the
#: same sentences the results screen shows: a reader who saw both should not
#: have to reconcile two accounts of one run.
_VERDICT: dict[Verdict, tuple[str, str]] = {
    Verdict.VERIFIED: (
        "Verified",
        "Every applicable check ran against the produced project and passed.",
    ),
    Verdict.PARTIALLY_VERIFIED: (
        "Partially verified",
        "The checks ran and some did not pass. They are listed below, with why.",
    ),
    Verdict.UNVERIFIED: (
        "Unverified",
        "Files were produced and nothing has been checked against the workbook "
        "they came from.",
    ),
    Verdict.FAILED: (
        "Failed",
        "The conversion did not finish, so there is no output to judge.",
    ),
}

_STATUS_WORD = {
    "converted": "Converted",
    "partial": "Partly converted",
    "ai_required": "Needs a draft",
    "unsupported": "Not supported",
    "failed": "Failed",
}

_CSS = """
:root { color-scheme: light dark; }
body { margin: 0; padding: 2.5rem 1.5rem; font: 15px/1.6 system-ui, sans-serif;
       max-width: 60rem; margin-inline: auto; }
h1 { font-size: 1.9rem; margin: 0 0 .25rem; letter-spacing: -.01em; }
h2 { font-size: 1.05rem; margin: 2.5rem 0 .75rem; text-transform: uppercase;
     letter-spacing: .08em; opacity: .6; font-weight: 600; }
.lead { font-size: 1.25rem; margin: 0 0 .5rem; }
.sub { opacity: .7; margin: 0 0 1.5rem; }
.verdict { border: 1px solid currentColor; border-radius: .5rem; padding: 1rem 1.25rem;
           margin: 1.5rem 0; }
.verdict strong { display: block; font-size: 1.1rem; margin-bottom: .25rem; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; padding: .5rem .75rem; border-bottom: 1px solid;
         border-color: color-mix(in srgb, currentColor 15%, transparent);
         vertical-align: top; }
th { font-weight: 600; opacity: .6; font-size: .8rem; text-transform: uppercase;
     letter-spacing: .05em; }
code, .mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .85em; }
.formula { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .8rem;
           opacity: .75; padding: .75rem; border-radius: .375rem;
           background: color-mix(in srgb, currentColor 6%, transparent);
           overflow-wrap: anywhere; }
footer { margin-top: 3rem; padding-top: 1rem; font-size: .8rem; opacity: .6;
         border-top: 1px solid color-mix(in srgb, currentColor 15%, transparent); }
"""


def _rows(cells: list[list[str]]) -> str:
    """Every cell is escaped here, so no caller has to remember to."""
    return "".join(
        "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>"
        for row in cells
    )


@dataclass(frozen=True)
class Risk:
    """One line of the "key risks" list: a count and what it is a count of."""

    count: int
    #: The sentence a reader sees. In the source's vocabulary, not the
    #: parser's - "table calculations", never "TABLE_CALC_UNSUPPORTED".
    sentence: str


def key_risks(report: ConversionReport, limit: int = 6) -> tuple[list[Risk], int]:
    """The few things a lead needs to know, and how many were left off.

    08-validation-engine.md, "Executive summary":

        > Then key risks, in the source's vocabulary rather than the parser's.
        >   3 advanced table calculations have no Power BI equivalent and need
        >     rewriting
        >   2 custom visualisations have no direct equivalent

    A flat list of 154 flags is not a summary; the full list already has its own
    section below and nothing is dropped from it. This picks the few worth
    reading first and returns the number it did not show, so the section can
    never imply it is the whole story.

    Only flags that changed an outcome are risks. A `converted` flag is a note
    about something that came across.

    Grouped on the reason **verbatim**. The engine already writes that sentence
    in the source's vocabulary - "this worksheet filter", "shelf field", "mark
    type" - so grouping on it needs no string surgery and invents no wording of
    its own. The cost is accepted knowingly: two flags that differ only in the
    object they name stay two lines rather than one. Cutting them at the quote
    to merge them produces fragments instead of sentences and leaks generated
    ids into a document meant to be forwarded.

    Ties break on the sentence, so the same run always produces the same list.
    """
    counts: dict[str, int] = {}
    for flag in report.flags:
        if flag.status.value == "converted":
            continue
        counts[flag.reason] = counts.get(flag.reason, 0) + 1

    ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    shown = [Risk(count=count, sentence=reason) for reason, count in ordered[:limit]]
    # Objects, not groups: a reader asking "what is not on this list" is asking
    # how many things, not how many kinds of thing.
    omitted = sum(counts.values()) - sum(risk.count for risk in shown)
    return shown, omitted


def _ai_note(count: int) -> str:
    """A bare zero here reads as "the model tried and produced nothing".

    Nothing was attempted: no provider is reachable from the conversion path
    yet. That is a different fact from a model that ran and helped with none of
    it, and the report says which one happened.
    """
    if count == 0:
        return (
            "Nothing was attempted - no provider was configured, so no "
            "expression was ever sent to a model."
        )
    return "Drafted by a model and accepted by a person before it was written."


def render_html(report: ConversionReport) -> str:
    label, meaning = _VERDICT[report.verdict]
    counts = report.compatibility
    name = report.project.name

    parts: list[str] = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>Conversion report — {escape(name)}</title>",
        f"<style>{_CSS}</style>",
        "</head><body>",
        f"<h1>{escape(name)}</h1>",
        f'<p class="sub">Tableau to Power BI · '
        f'<span class="mono">{escape(str(report.project.project_id))}</span></p>',
        # The lead line, with its denominator. Never a bare percentage.
        f'<p class="lead"><strong>{counts.converted}</strong> of '
        f"<strong>{counts.total}</strong> objects converted · "
        f"{counts.partial + counts.ai_required} need review · "
        f"{counts.unsupported} unsupported · {counts.failed} failed</p>",
        f'<div class="verdict"><strong>{escape(label)}</strong>{escape(meaning)}</div>',
    ]

    # How, not how much. The two are different questions and a lead asking
    # "how much of this was automated" is asking this one.
    means = means_of_conversion(report)
    parts.append("<h2>How it was converted</h2>")
    parts.append(
        "<table><tr><th>Means</th><th>Objects</th><th>What that means</th></tr>"
        + _rows(
            [
                [
                    "By rule",
                    str(means.by_rule),
                    "Translated by a rule in the engine, with no model involved.",
                ],
                [
                    "AI-assisted",
                    str(means.ai_assisted),
                    _ai_note(means.ai_assisted),
                ],
                [
                    "By hand",
                    str(means.by_hand),
                    "Reported for a person to rebuild. Each one is listed below.",
                ],
            ]
        )
        + "</table>"
    )
    parts.append(
        f'<p class="sub">These sum to the {report.compatibility.total} objects '
        "counted above, which is the same denominator.</p>"
    )

    # The few things worth reading first. The full list is still below and
    # nothing is dropped from it; this is what a lead reads instead of 154 rows.
    risks, omitted = key_risks(report)
    if risks:
        parts.append("<h2>Key risks</h2>")
        parts.append(
            "<table><tr><th>Objects</th><th>What needs attention</th></tr>"
            + _rows([[str(risk.count), risk.sentence] for risk in risks])
            + "</table>"
        )
        if omitted:
            # A shortened list that does not say it is shortened reads as the
            # whole story.
            parts.append(
                f'<p class="sub">and {omitted} more, every one of them listed '
                "in full below.</p>"
            )

    if report.validation is not None:
        parts.append("<h2>What the checks found</h2>")
        parts.append(
            "<table><tr><th>Category</th><th>Passed</th><th>Applicable</th></tr>"
            + _rows(
                [
                    [name_, str(category.passed), str(category.checks)]
                    for name_, category in report.validation.categories.items()
                ]
            )
            + "</table>"
        )
        if report.validation.formula:
            # The derivation, beside the score it produced. A score a reader
            # cannot follow is decoration.
            parts.append(
                f'<p class="formula">{escape(report.validation.formula)}</p>'
            )
        notable = [
            rule
            for rule in report.validation.rules
            if rule.status in {"FAIL", "WARNING"}
        ]
        if notable:
            parts.append("<h2>Checks that did not pass</h2>")
            parts.append(
                "<table><tr><th>Check</th><th>Result</th><th>Finding</th></tr>"
                + _rows([[r.rule_id, r.status, r.note] for r in notable])
                + "</table>"
            )
        parts.append(
            "<p>Numerical equivalence: not measured. "
            + escape(report.validation.numerical.reason)
            + "</p>"
        )
    else:
        parts.append("<h2>What the checks found</h2>")
        parts.append(
            "<p>Validation has not run for this conversion, so nothing in this "
            "report has been checked against the workbook it came from.</p>"
        )

    # Always present, even when empty, because a report with no such section
    # reads as a run with nothing left to do.
    parts.append("<h2>What did not come across</h2>")
    if report.flags:
        parts.append(
            "<table><tr><th>Object</th><th>Outcome</th><th>Stage</th>"
            "<th>Why</th></tr>"
            + _rows(
                [
                    [
                        flag.item,
                        _STATUS_WORD.get(flag.status.value, flag.status.value),
                        flag.stage.value,
                        flag.reason,
                    ]
                    for flag in report.flags
                ]
            )
            + "</table>"
        )
    else:
        parts.append("<p>Every object the engine considered came across.</p>")

    # The record of what *did* come across. The section above says what did not;
    # only this can defend a transformation that worked, because it carries the
    # expression that was actually emitted beside the one it came from.
    parts.append("<h2>Audit trail</h2>")
    if report.audit:
        crossed = sum(1 for entry in report.audit if entry.outcome.value == "crossed")
        parts.append(
            f"<p>{len(report.audit)} objects were handled: {crossed} came "
            f"across, {len(report.audit) - crossed} were held for a person. "
            "Ordered as the run recorded them.</p>"
        )
        parts.append(
            "<table><tr><th>Stage</th><th>Object</th><th>Outcome</th>"
            "<th>From</th><th>To</th></tr>"
            + _rows(
                [
                    [
                        entry.stage.value,
                        entry.name,
                        "Came across" if entry.outcome.value == "crossed" else "Held",
                        entry.source or entry.detail,
                        entry.result,
                    ]
                    for entry in report.audit
                ]
            )
            + "</table>"
        )
    else:
        parts.append(
            "<p>This conversion has no recording, so there is no object-by-object "
            "account of it. The counts and refusals above still hold; what is "
            "missing is the order the run handled things in.</p>"
        )

    parts.append(
        "<footer>Produced offline. The workbook this describes was read on "
        "this machine and sent nowhere.</footer></body></html>"
    )
    return "\n".join(parts) + "\n"
