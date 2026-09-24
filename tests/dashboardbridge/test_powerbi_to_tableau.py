"""Converting a Power BI project into a Tableau workbook, end to end in the engine.

`SPEC-powerbi-to-tableau-web.md` FR4-FR6 and AC4, AC6, AC7, AC8. The API and
the web application only ever see `convert_powerbi_to_tableau`; everything they
show about this direction is read off what it returns.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest
from dashboardbridge_contracts.enums import ConversionStatus, Stage

from engines.conversion.to_tableau import (
    NoSemanticModel,
    convert_powerbi_to_tableau,
)
from tests.support.synthetic_pbip import TYPICAL, project_zip

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "pbip"


def _zipped(directory: Path, only: str | None = None) -> bytes:
    """The fixture as a person would send it: the project folder, zipped."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory).as_posix()
            if path.is_file() and (only is None or relative.startswith(only)):
                archive.write(path, relative)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def outcome(tmp_path_factory):
    out = tmp_path_factory.mktemp("to-tableau")
    return convert_powerbi_to_tableau(_zipped(FIXTURE), out, "Retail")


def _objects(model) -> int:
    return (
        sum(1 + len(table.columns) for table in model.all_tables())
        + len(model.relationships)
        + len(model.parameters)
        + len(model.visuals)
        + len(model.dashboards)
    )


# --- what is produced ----------------------------------------------------------


def test_it_produces_one_tableau_workbook(outcome):
    produced = list(outcome.project_dir.glob("*.twb"))
    assert [path.name for path in produced] == ["Retail.twb"]


def test_the_counts_sum_to_the_whole_and_the_whole_is_every_object(outcome):
    counts = outcome.compatibility
    parts = (
        counts.converted
        + counts.partial
        + counts.ai_required
        + counts.unsupported
        + counts.failed
    )
    assert parts == counts.total
    assert counts.total == _objects(outcome.model)


def test_every_flagged_object_is_counted_as_what_its_worst_flag_says(outcome):
    counts = outcome.compatibility
    worst = {}
    rank = [
        ConversionStatus.CONVERTED,
        ConversionStatus.PARTIAL,
        ConversionStatus.AI_REQUIRED,
        ConversionStatus.UNSUPPORTED,
        ConversionStatus.FAILED,
    ]
    for flag in outcome.flags:
        # By ref: a page and its visual are often named the same.
        current = worst.get(flag.ref, ConversionStatus.CONVERTED)
        worst[flag.ref] = max(current, flag.status, key=rank.index)
    assert counts.unsupported == sum(
        1 for status in worst.values() if status is ConversionStatus.UNSUPPORTED
    )
    assert counts.partial == sum(
        1 for status in worst.values() if status is ConversionStatus.PARTIAL
    )


def test_no_model_is_offered_in_this_direction(outcome):
    """Deterministic only (spec §7, Q3). Nothing waits on a model."""
    assert outcome.compatibility.ai_required == 0


def test_the_refused_measure_is_reported_with_its_reason(outcome):
    refused = [
        flag
        for flag in outcome.flags
        if flag.item == "Sales.Revenue per Unit" and flag.stage is Stage.TRANSLATE
    ]
    assert len(refused) == 1
    assert "DIVIDE" in refused[0].reason


def test_the_timeline_carries_both_sides_of_a_translated_measure(outcome):
    events = {event.ref: event for event in outcome.timeline.events}
    total = events["Sales.Total Revenue"]
    assert total.outcome == "crossed"
    assert total.source == "SUM(Sales[Revenue])"
    assert total.result == "SUM([Revenue])"


def test_the_timeline_holds_the_refused_measure_with_its_dax(outcome):
    events = {event.ref: event for event in outcome.timeline.events}
    held = events["Sales.Revenue per Unit"]
    assert held.outcome == "held"
    assert "DIVIDE" in held.source
    assert held.result == ""


def test_the_timeline_names_every_object_once(outcome):
    refs = [event.ref for event in outcome.timeline.events]
    assert len(refs) == len(set(refs)) == _objects(outcome.model)


def test_the_model_is_named_after_the_project(outcome):
    assert outcome.model.name == "Retail"


# --- edge cases ----------------------------------------------------------------


def test_a_project_with_no_semantic_model_is_refused(tmp_path):
    """Visuals cannot be bound without the model they read (spec §5)."""
    with pytest.raises(NoSemanticModel):
        convert_powerbi_to_tableau(
            _zipped(FIXTURE, only="Retail.Report"), tmp_path, "Retail"
        )


def test_a_semantic_model_with_no_report_converts_to_a_workbook_with_no_sheets(tmp_path):
    produced = convert_powerbi_to_tableau(
        _zipped(FIXTURE, only="Retail.SemanticModel"), tmp_path, "Retail"
    )
    text = next(produced.project_dir.glob("*.twb")).read_text(encoding="utf-8")
    assert "<worksheet " not in text
    assert produced.compatibility.failed == 0


# --- determinism and the budget ------------------------------------------------

_DIGEST = """
import hashlib, json, sys, tempfile
from pathlib import Path
from engines.conversion.to_tableau import convert_powerbi_to_tableau
from tests.support.synthetic_pbip import project_zip
with tempfile.TemporaryDirectory() as out:
    outcome = convert_powerbi_to_tableau(project_zip(), Path(out), "Synthetic")
    digest = hashlib.sha256()
    for path in sorted(Path(out).rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(out).as_posix().encode())
            digest.update(path.read_bytes())
    digest.update(json.dumps([f.model_dump(mode="json") for f in outcome.flags]).encode())
    print(digest.hexdigest())
"""


def _digest_in_a_new_process(seed: str) -> str:
    paths = [str(ROOT / "packages" / "contracts" / "src"), str(ROOT)]
    environment = dict(
        os.environ,
        PYTHONHASHSEED=seed,
        PYTHONPATH=os.pathsep.join([*paths, os.environ.get("PYTHONPATH", "")]),
    )
    finished = subprocess.run(
        [sys.executable, "-c", _DIGEST],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert finished.returncode == 0, finished.stderr[-2000:]
    return finished.stdout.strip()


def test_the_output_and_flags_do_not_depend_on_the_hash_seed():
    """Separate processes, because set order only varies between them (`P8.3`)."""
    digests = {_digest_in_a_new_process(seed) for seed in ("0", "1", "4242")}
    assert len(digests) == 1


def test_a_typical_project_converts_inside_the_budget(tmp_path):
    """Spec AC8: a ceiling to guard against regression, not a number to quote."""
    data = project_zip(TYPICAL)
    started = time.perf_counter()
    produced = convert_powerbi_to_tableau(data, tmp_path, "Synthetic")
    elapsed = time.perf_counter() - started
    assert elapsed < 10.0, f"{elapsed:.2f}s against a 10s analysis budget"
    # The corpus is not all happy path: DIVIDE is refused, tooltips unplaced.
    assert produced.compatibility.unsupported > 0
    assert produced.compatibility.partial > 0
