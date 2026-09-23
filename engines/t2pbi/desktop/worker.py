"""Job summary shaping for the desktop shell.

`run_job` runs a conversion and returns a display-ready summary. It is pure: no
UI toolkit, no window, so it is fully testable headlessly and is shared by the
shell and by tests. See docs/specs/modules/desktop.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from engines.t2pbi.ir import Severity
from engines.t2pbi.pipeline import run


@dataclass
class CalcResult:
    """One calculated field's outcome — drives the report ledger."""

    table: str
    name: str
    formula: str
    dax: str | None  # None means it needs manual work

    @property
    def converted(self) -> bool:
        return self.dax is not None


@dataclass
class FlagItem:
    item: str
    severity: str
    reason: str
    stage: str


@dataclass
class JobSummary:
    pbip_path: str
    report_path: str
    out_dir: str
    stats: dict[str, int]
    calcs: list[CalcResult] = field(default_factory=list)
    flags: list[FlagItem] = field(default_factory=list)

    def headline(self) -> str:
        s = self.stats
        return (
            f"{s['tables']} tables · {s['columns']} columns · "
            f"{s['calculated_translated']}/{s['calculated_fields']} calcs → DAX · "
            f"{s['manual_flags']} need manual work"
        )


def run_job(
    input_path: str | Path,
    out_dir: str | Path,
    name: str | None = None,
    progress_cb: Callable[[str, int], None] | None = None,
) -> JobSummary:
    """Run the full conversion. Pure: no Qt, no UI. Raises on invalid input."""
    result = run(input_path, out_dir, name, progress_cb=progress_cb)
    wb = result.workbook

    calcs = [
        CalcResult(table=t.name, name=c.display_name, formula=c.formula or "", dax=c.dax)
        for t in wb.all_tables()
        for c in t.columns
        if c.is_calculated
    ]
    calcs.sort(key=lambda c: (not c.converted, c.table, c.name))

    flags = [
        FlagItem(item=f.item, severity=f.severity.value, reason=f.reason, stage=f.stage)
        for f in wb.flags
    ]
    sev_rank = {Severity.MANUAL.value: 0, Severity.WARNING.value: 1, Severity.INFO.value: 2}
    flags.sort(key=lambda f: (sev_rank.get(f.severity, 9), f.item))

    return JobSummary(
        pbip_path=str(result.pbip_path),
        report_path=str(result.report_path),
        out_dir=str(out_dir),
        stats=result.stats,
        calcs=calcs,
        flags=flags,
    )
