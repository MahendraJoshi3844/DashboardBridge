"""The workspace assistant's deterministic half: inventory, checks and rewrites.

Everything here is a rule with a stated effect. It runs before any model is
asked anything (AGENTS.md rule 4), its findings are what a model summary is
allowed to talk about, and a rewrite it offers says exactly what it changes.
Nothing here edits the project: a proposal is applied by a person, into their
draft changes, or not at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from dashboardbridge_contracts import (
    AssistantFinding,
    AssistantMessage,
    AssistantProposal,
    AssistantStepResult,
    WorkspaceHeld,
    WorkspaceTable,
)

from app.services.workspace import ReadPage
from engines.dax import references_in, visible

#: `fromColumn: Sales.'Store Key'` - the table is everything before the dot.
_REL_END = re.compile(r"^\t(from|to)Column:\s*(?:'((?:[^']|'')+)'|([^.\s]+))\.")


@dataclass
class Context:
    """What the checks look at: the newest version, read back from its files."""

    tables: list[WorkspaceTable]
    pages: list[ReadPage]
    relationships: list[tuple[str, str]]
    held: list[WorkspaceHeld]

    @property
    def measures(self) -> dict[str, set[str]]:
        return {table.name: {m.name for m in table.measures} for table in self.tables}


def relationships_of(files: dict[str, bytes]) -> list[tuple[str, str]]:
    """`(from table, to table)` for every relationship in the model's TMDL."""
    found: list[tuple[str, str]] = []
    for path, body in sorted(files.items()):
        if not path.endswith("relationships.tmdl"):
            continue
        ends: list[str] = []
        for line in body.decode("utf-8", errors="replace").splitlines():
            match = _REL_END.match(line)
            if match:
                ends.append((match.group(2) or match.group(3)).replace("''", "'"))
                if len(ends) == 2:
                    found.append((ends[0], ends[1]))
                    ends = []
            elif line.startswith("relationship "):
                ends = []
    return found


# --- inventory -------------------------------------------------------------------


def inventory(ctx: Context) -> AssistantStepResult:
    tables = ctx.tables
    calculated = sum(
        1 for table in tables if any(p.source_kind == "calculated" for p in table.partitions)
    )
    visuals = sum(len(page.visuals) for page in ctx.pages)
    text = (
        f"Model inventory: {len(tables)} tables ({calculated} calculated), "
        f"{sum(len(t.columns) for t in tables)} columns, "
        f"{sum(len(t.measures) for t in tables)} measures, "
        f"{sum(len(t.partitions) for t in tables)} table sources, "
        f"{len(ctx.relationships)} relationships, {visuals} visuals on "
        f"{len(ctx.pages)} pages, {len(ctx.held)} calculations held for a person."
    )
    return AssistantStepResult(
        step="inventory",
        title="Model inventory",
        messages=[AssistantMessage(role="system", text=text)],
    )


# --- DAX ---------------------------------------------------------------------------


def _top_level(expression: str) -> list[tuple[int, str]]:
    """Operators outside any bracket, string or comment, with their positions."""
    text = visible(expression)
    depth = 0
    found: list[tuple[int, str]] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif depth == 0:
            pair = text[index : index + 2]
            if pair in {"&&", "||", "<=", ">=", "<>"}:
                found.append((index, pair))
                index += 2
                continue
            if char in "+-*/&=<>^":
                found.append((index, char))
        index += 1
    return found


def divide_rewrite(expression: str) -> str | None:
    """`A / B` as `DIVIDE(A, B)`, when that is the whole expression.

    Only a single top-level division with nothing else at top level is
    rewritten; anything more and the operator precedence would have to be
    re-derived, which is a parse this does not do. The rewrite changes one
    thing and says so: division by zero gives BLANK instead of Infinity/NaN.
    """
    operators = _top_level(expression)
    if [op for _, op in operators] != ["/"]:
        return None
    position = operators[0][0]
    left, right = expression[:position].strip(), expression[position + 1 :].strip()
    if not left or not right:
        return None
    return f"DIVIDE({left}, {right})"


def check_references(ctx: Context, items: list[str]) -> AssistantStepResult:
    """Every reference in every chosen measure names something in the model."""
    columns = {
        table.name.lower(): {c.name.lower() for c in table.columns}
        | {m.name.lower() for m in table.measures}
        for table in ctx.tables
    }
    measures = {m.name.lower() for table in ctx.tables for m in table.measures}
    every_column = {c.name.lower() for table in ctx.tables for c in table.columns}

    findings: list[AssistantFinding] = []
    proposals: list[AssistantProposal] = []
    checked = clean = 0
    for table in ctx.tables:
        for measure in table.measures:
            item = f"{table.name}.{measure.name}"
            if items and item not in items:
                continue
            checked += 1
            problems = []
            for reference in references_in(measure.expression):
                if reference.table:
                    fields = columns.get(reference.table.lower())
                    if fields is None:
                        problems.append(f"{reference.raw} names a table that is not in the model")
                    elif reference.name.lower() not in fields:
                        problems.append(f"{reference.raw}: {reference.table} has no such column or measure")
                elif reference.name.lower() not in measures | every_column:
                    problems.append(f"{reference.raw} names no measure or column")
            for problem in problems:
                findings.append(
                    AssistantFinding(severity="error", item=item, message=problem, check="references")
                )
            rewritten = divide_rewrite(measure.expression)
            if rewritten:
                findings.append(
                    AssistantFinding(
                        severity="warning",
                        item=item,
                        message="Divides with '/', which returns Infinity (or NaN for 0/0) when the denominator is zero. DIVIDE() returns BLANK instead.",
                        check="divide",
                    )
                )
                proposals.append(
                    AssistantProposal(
                        kind="measure",
                        table=table.name,
                        name=measure.name,
                        expression=rewritten,
                        current=measure.expression,
                        reason="Rewritten with DIVIDE(). The one change: a zero denominator gives BLANK rather than Infinity or NaN.",
                        origin="rule",
                    )
                )
            if not problems and not rewritten:
                clean += 1

    count = f"{checked} measure{'s' if checked != 1 else ''}"
    if items and not checked:
        # A held calculation is not a measure yet, so there is nothing of it
        # to check here; drafting it is the next step's job.
        return AssistantStepResult(
            step="check_references",
            title="Validate calculations",
            messages=[
                AssistantMessage(
                    role="system",
                    text="The selection is not a measure in the model yet, so there is nothing to check; a held calculation is drafted in the next step.",
                )
            ],
        )
    text = (
        f"Checked {count}: {clean} clean, "
        f"{sum(1 for f in findings if f.severity == 'error')} broken references, "
        f"{len(proposals)} divisions that could use DIVIDE()."
    )
    return AssistantStepResult(
        step="check_references",
        title="Validate calculations",
        messages=[AssistantMessage(role="system", text=text)],
        findings=findings,
        proposals=proposals,
        checks_run=checked,
        checks_clean=clean,
    )


# --- Power Query -------------------------------------------------------------------


def _is_placeholder(expression: str) -> bool:
    """The converter's schema-only source: an empty `#table(..., {})`."""
    compact = re.sub(r"\s+", "", expression)
    return "#table(" in compact and ",{})" in compact


def _split_top(text: str, separator: str = ",") -> list[str]:
    parts: list[str] = []
    depth = 0
    quoted = False
    start = 0
    for index, char in enumerate(text):
        if char == '"':
            quoted = not quoted
        elif not quoted and char in "([{":
            depth += 1
        elif not quoted and char in ")]}":
            depth -= 1
        elif not quoted and depth == 0 and char == separator:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return parts


def format_m(expression: str) -> str | None:
    """A one-line `let ... in ...` laid out one step per line. Nothing else.

    Returns None for anything already on several lines, or not shaped as a let
    expression, rather than reformatting what it did not fully understand.
    """
    text = expression.strip()
    if "\n" in text or not text.lower().startswith("let "):
        return None
    body = text[4:]
    # The last top-level ` in ` closes the let.
    depth = 0
    quoted = False
    split_at = -1
    for index, char in enumerate(body):
        if char == '"':
            quoted = not quoted
        elif not quoted and char in "([{":
            depth += 1
        elif not quoted and char in ")]}":
            depth -= 1
        elif not quoted and depth == 0 and body[index : index + 4] == " in ":
            split_at = index
    if split_at < 0:
        return None
    steps = [step for step in _split_top(body[:split_at]) if step]
    result = body[split_at + 4 :].strip()
    if not steps or not result:
        return None
    lines = ["let"]
    lines += [f"    {step}{',' if i < len(steps) - 1 else ''}" for i, step in enumerate(steps)]
    lines += ["in", f"    {result}"]
    return "\n".join(lines)


def check_mquery(ctx: Context, items: list[str]) -> AssistantStepResult:
    findings: list[AssistantFinding] = []
    checked = clean = 0
    for table in ctx.tables:
        if items and table.name not in items:
            continue
        for partition in table.partitions:
            checked += 1
            if partition.source_kind == "calculated":
                clean += 1
                continue
            problems = []
            if _is_placeholder(partition.expression):
                problems.append(
                    AssistantFinding(
                        severity="warning",
                        item=table.name,
                        message="Schema-only source: an empty #table with no rows. Point it at your data before publishing.",
                        check="placeholder_source",
                    )
                )
            if not partition.expression.strip().lower().startswith("let"):
                problems.append(
                    AssistantFinding(
                        severity="warning",
                        item=table.name,
                        message="The source is not a let expression, which is unusual for Power Query.",
                        check="m_shape",
                    )
                )
            findings.extend(problems)
            if not problems:
                clean += 1
    text = (
        f"Checked {checked} table source{'s' if checked != 1 else ''}: {clean} ready, "
        f"{sum(1 for f in findings if f.check == 'placeholder_source')} still schema-only placeholders."
    )
    return AssistantStepResult(
        step="check_mquery",
        title="Validate M-Query",
        messages=[AssistantMessage(role="system", text=text)],
        findings=findings,
        checks_run=checked,
        checks_clean=clean,
    )


def format_mquery(ctx: Context, items: list[str]) -> AssistantStepResult:
    proposals: list[AssistantProposal] = []
    for table in ctx.tables:
        if items and table.name not in items:
            continue
        for partition in table.partitions:
            if partition.source_kind == "calculated":
                continue
            formatted = format_m(partition.expression)
            if formatted and formatted != partition.expression:
                proposals.append(
                    AssistantProposal(
                        kind="partition",
                        table=table.name,
                        name=partition.name,
                        expression=formatted,
                        current=partition.expression,
                        reason="Laid out one step per line. The query itself is unchanged.",
                        origin="rule",
                    )
                )
    text = (
        f"{len(proposals)} Power Query source{'s' if len(proposals) != 1 else ''} can be laid out for reading."
        if proposals
        else "Every Power Query source is already laid out; nothing to format."
    )
    return AssistantStepResult(
        step="format_mquery",
        title="Fix M-Query",
        messages=[AssistantMessage(role="system", text=text)],
        proposals=proposals,
    )


# --- model health --------------------------------------------------------------------


def _used_fields(ctx: Context) -> set[tuple[str, str]]:
    used: set[tuple[str, str]] = set()
    for table in ctx.tables:
        for measure in table.measures:
            for reference in references_in(measure.expression):
                used.add(((reference.table or table.name).lower(), reference.name.lower()))
    for page in ctx.pages:
        for visual in page.visuals:
            for entry in visual.fields:
                reference = entry.split(": ", 1)[-1]
                if "." in reference:
                    table, name = reference.split(".", 1)
                    used.add((table.lower(), name.lower()))
    return used


def model_health(ctx: Context) -> AssistantStepResult:
    findings: list[AssistantFinding] = []
    checks = 0
    clean = 0

    # 1. Calculations the converter could not translate.
    checks += 1
    for held in ctx.held:
        findings.append(
            AssistantFinding(
                severity="error",
                item=held.item,
                message=f"Held for a person: {held.reason}",
                check="held",
            )
        )
    clean += not ctx.held

    # 2. Columns nothing uses.
    checks += 1
    used = _used_fields(ctx)
    unused_any = False
    for table in ctx.tables:
        if any(p.source_kind == "calculated" for p in table.partitions):
            continue
        unused = [c.name for c in table.columns if (table.name.lower(), c.name.lower()) not in used]
        if unused:
            unused_any = True
            shown = ", ".join(unused[:6]) + ("…" if len(unused) > 6 else "")
            findings.append(
                AssistantFinding(
                    severity="info",
                    item=table.name,
                    message=f"{len(unused)} of {len(table.columns)} columns are used by no measure or visual ({shown}). Hide or remove what is not needed.",
                    check="unused_columns",
                )
            )
    clean += not unused_any

    # 3. Columns with no data type.
    checks += 1
    untyped = [
        f"{table.name}[{column.name}]"
        for table in ctx.tables
        for column in table.columns
        if not column.data_type
    ]
    for name in untyped:
        findings.append(
            AssistantFinding(severity="warning", item=name, message="No data type is recorded.", check="data_type")
        )
    clean += not untyped

    # 4. Tables that share a column name and are not related.
    checks += 1
    related = {frozenset(pair) for pair in ctx.relationships}
    physical = [t for t in ctx.tables if not any(p.source_kind == "calculated" for p in t.partitions)]
    gaps = 0
    for index, left in enumerate(physical):
        for right in physical[index + 1 :]:
            shared = {c.name for c in left.columns} & {c.name for c in right.columns}
            if shared and frozenset((left.name, right.name)) not in related:
                gaps += 1
                findings.append(
                    AssistantFinding(
                        severity="info",
                        item=f"{left.name} / {right.name}",
                        message=f"Share {', '.join(sorted(shared)[:3])} but are not related. Check whether a relationship is missing; a shared name alone does not make one.",
                        check="relationships",
                    )
                )
    clean += not gaps

    # 5. Sources that still hold no data.
    checks += 1
    placeholders = [
        table.name
        for table in ctx.tables
        for partition in table.partitions
        if partition.source_kind != "calculated" and _is_placeholder(partition.expression)
    ]
    if placeholders:
        findings.append(
            AssistantFinding(
                severity="warning",
                item=", ".join(placeholders[:6]) + ("…" if len(placeholders) > 6 else ""),
                message=f"{len(placeholders)} table source{'s are' if len(placeholders) != 1 else ' is'} still a schema-only placeholder.",
                check="placeholder_source",
            )
        )
    clean += not placeholders

    text = f"Model health: {clean} of {checks} checks found nothing; {len(findings)} findings."
    return AssistantStepResult(
        step="model_health",
        title="Model health",
        messages=[AssistantMessage(role="system", text=text)],
        findings=findings,
        checks_run=checks,
        checks_clean=clean,
    )


# --- what a model is told -------------------------------------------------------------


def _findings(ctx: Context) -> list[AssistantFinding]:
    return (
        check_references(ctx, []).findings
        + check_mquery(ctx, []).findings
        + model_health(ctx).findings
    )


def brief(ctx: Context, detail: bool = False) -> str:
    """What a model is told about the model: names, counts and findings.

    Never data, never a file path. Kept small on purpose: a local 8B model on a
    CPU reads a few hundred tokens a second, so a brief listing every column
    and formula took minutes before a word came back. Findings are grouped by
    check with a few examples each. `detail` adds table and measure names for
    chat, where a question may be about one of them; formulas are never sent.
    """
    lines = [inventory(ctx).messages[0].text]
    groups: dict[str, list[AssistantFinding]] = {}
    for finding in _findings(ctx):
        groups.setdefault(finding.check, []).append(finding)
    lines.append("FINDINGS BY CHECK:")
    if not groups:
        lines.append("- none")
    for check, found in sorted(groups.items()):
        examples = "; ".join(f"{f.item}: {f.message[:110]}" for f in found[:3])
        lines.append(f"- {check} ({len(found)} x {found[0].severity}): {examples}")
    if detail:
        lines.append("TABLES:")
        for table in ctx.tables[:30]:
            columns = ", ".join(c.name for c in table.columns[:15])
            more = f" (+{len(table.columns) - 15} more)" if len(table.columns) > 15 else ""
            measures = ", ".join(m.name for m in table.measures[:15])
            lines.append(f"- {table.name}: columns {columns}{more}" + (f"; measures {measures}" if measures else ""))
    return "\n".join(lines)


def draft_problems(expression: str, source: str, ctx: Context) -> list[str]:
    """Why a model's DAX draft cannot be offered, checked against this model.

    Run after the proposal gauntlet and stricter than it, because llama3.1
    returned `[Parameters].[Commission Rate]` - Tableau's syntax - and
    `MIN(Sales Commission.Base)` - not DAX at all - and both passed it. A draft
    that names something the model does not hold, or no longer names anything
    the source named, is not a proposal worth a person's review.
    """
    problems: list[str] = []
    if "].[" in expression:
        problems.append("it uses Tableau's [Source].[Field] form, which is not DAX")
    references = references_in(expression)
    if "[" in source and not references:
        problems.append("it names none of the fields the Tableau formula uses")
    tables = {
        t.name.lower(): {c.name.lower() for c in t.columns} | {m.name.lower() for m in t.measures}
        for t in ctx.tables
    }
    names = {n for fields in tables.values() for n in fields}
    for reference in references:
        if reference.table:
            fields = tables.get(reference.table.lower())
            if fields is None or reference.name.lower() not in fields:
                problems.append(f"{reference.raw} is not in the model")
        elif reference.name.lower() not in names:
            problems.append(f"{reference.raw} is not in the model")
    return problems
