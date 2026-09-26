"""The performance budget and the determinism proof (`P8.2`, `P8.3`).

Both need a corpus the repository did not have. The largest hand-written fixture
is 5.5 kB: a thirty-second budget measured against it says nothing, and a
determinism proof over five tables and one worksheet exercises almost none of
the ordering that could vary. `tests/support/synthetic.py` generates one to a
stated shape, deterministically, because a timing comparison needs identical
input between runs and a determinism proof over a varying input proves nothing.

## What the determinism test does that the existing one could not

`test_converting_the_same_workbook_twice_produces_identical_output` runs both
conversions **in one process**, so it cannot see the most likely source of
nondeterminism there is: set and dict iteration order, which Python varies by
`PYTHONHASHSEED` *per process*. Two runs in one interpreter share a seed and
agree with each other no matter how much unordered iteration the pipeline does.

So this runs the conversion in separate interpreters under four different seeds
and compares a hash of every byte of every file produced. It passes today, and
that is a stronger statement than the same-process test can make.

## What the budget is, and what it is not

`analysis < 10s, conversion < 30s for a typical workbook`. The generated typical
workbook converts in well under a second, so these assertions are a **ceiling
against regression**, not a measurement anyone should quote as the product's
speed. And the corpus is generated: a real workbook carries thumbnails, styles
and formatting this does not, so the number here is a floor on what a real one
costs, not a prediction of it.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from t2pbi import pipeline
from tests.support.synthetic import LARGE, TYPICAL, workbook_xml

ROOT = Path(__file__).resolve().parents[1]

#: From the roadmap, verbatim: "analysis < 10s, conversion < 30s for a typical
#: workbook". A ceiling, not a target.
ANALYSIS_BUDGET_SECONDS = 10.0
CONVERSION_BUDGET_SECONDS = 30.0


def _written(tmp_path: Path, shape) -> Path:
    path = tmp_path / "workbook.twb"
    path.write_bytes(workbook_xml(shape))
    return path


# --- the budget -------------------------------------------------------------------


def test_a_typical_workbook_converts_inside_the_budget(tmp_path):
    """The whole pipeline: extract, parse, map, translate, generate, report."""
    source = _written(tmp_path, TYPICAL)

    started = time.perf_counter()
    pipeline.run(source, tmp_path / "out")
    elapsed = time.perf_counter() - started

    assert elapsed < CONVERSION_BUDGET_SECONDS, (
        f"{elapsed:.2f}s for {TYPICAL.tables} tables, {TYPICAL.columns} columns, "
        f"{TYPICAL.calculations} calculations, {TYPICAL.worksheets} worksheets"
    )


def test_parsing_a_typical_workbook_is_inside_the_analysis_budget(tmp_path):
    """Analysis is parse plus counting, so parse is the part with a budget."""
    from t2pbi.core.parse import parse_workbook

    xml = workbook_xml(TYPICAL)

    started = time.perf_counter()
    parse_workbook(xml)
    elapsed = time.perf_counter() - started

    assert elapsed < ANALYSIS_BUDGET_SECONDS, f"{elapsed:.2f}s to parse {len(xml)} bytes"


def test_a_workbook_far_larger_than_expected_still_finishes(tmp_path):
    """Deliberately past anything expected in practice.

    The budget is stated for a typical workbook; this is here so that a change
    turning a linear pass into a quadratic one shows up as a failure rather than
    as a support ticket. 20 tables, 800 columns, 300 calculations, 120 sheets.
    """
    source = _written(tmp_path, LARGE)

    started = time.perf_counter()
    pipeline.run(source, tmp_path / "out")
    elapsed = time.perf_counter() - started

    assert elapsed < CONVERSION_BUDGET_SECONDS, (
        f"{elapsed:.2f}s for {LARGE.columns} columns and {LARGE.worksheets} sheets"
    )


def test_the_generated_corpus_is_not_all_happy_path(tmp_path):
    """A budget measured on a corpus that all converts measures one branch.

    Refusal does real work - it builds the reason and the flag - so the corpus
    contains formulas the translator refuses, and this keeps that true.
    """
    result = pipeline.run(_written(tmp_path, TYPICAL), tmp_path / "out")
    calculations = [
        column
        for table in result.workbook.all_tables()
        for column in table.columns
        if column.is_calculated
    ]
    converted = [column for column in calculations if column.dax]

    assert calculations, "the corpus has no calculations at all"
    assert converted, "nothing converted, so the timing is all refusal"
    assert len(converted) < len(calculations), "everything converted, so no refusal path"


# --- the determinism proof ---------------------------------------------------------


_PROBE = '''
import hashlib, pathlib, sys, tempfile
sys.path[:0] = [{paths}]
from tests.support.synthetic import workbook_xml, TYPICAL
from t2pbi import pipeline

scratch = pathlib.Path(tempfile.mkdtemp())
source = scratch / "w.twb"
source.write_bytes(workbook_xml(TYPICAL))
out = scratch / "out"
pipeline.run(source, out)

digest = hashlib.sha256()
for path in sorted(out.rglob("*")):
    if path.is_file():
        digest.update(str(path.relative_to(out)).replace("\\\\", "/").encode())
        digest.update(path.read_bytes())
print(digest.hexdigest())
'''


def _digest_under(seed: str, script: Path) -> str:
    environment = dict(os.environ, PYTHONHASHSEED=seed)
    finished = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=environment,
        cwd=str(ROOT),
    )
    assert finished.returncode == 0, finished.stderr[-2000:]
    return finished.stdout.strip()


@pytest.fixture(scope="module")
def digests(tmp_path_factory) -> list[str]:
    """The same conversion, in four interpreters, under four hash seeds."""
    scratch = tmp_path_factory.mktemp("determinism")
    script = scratch / "probe.py"
    paths = ", ".join(
        repr(str(ROOT / part))
        for part in (Path("packages/contracts/src"), Path("."))
    )
    script.write_text(_PROBE.format(paths=paths), encoding="utf-8")
    return [_digest_under(seed, script) for seed in ("0", "1", "12345", "99999")]


def test_the_same_workbook_produces_identical_bytes_in_a_separate_process(digests):
    """Every file, every byte, hashed with its path so a rename is a difference."""
    assert len(set(digests)) == 1, dict(zip(("0", "1", "12345", "99999"), digests))


def test_the_output_does_not_depend_on_the_hash_seed(digests):
    """The claim the same-process test cannot make.

    Python randomises set and dict iteration order per process. Two runs in one
    interpreter share that seed, so unordered iteration anywhere in the pipeline
    would still agree with itself. Four seeds is what makes this a proof rather
    than a coincidence.
    """
    assert digests[0] == digests[-1]
    assert all(digest for digest in digests), "a run produced no output at all"


def test_the_proof_would_notice_a_difference(tmp_path):
    """The control. A determinism proof that cannot fail is not evidence.

    A hash over a *different* workbook must differ, or the digest is not
    reading the output it claims to read.
    """
    from tests.support.synthetic import Shape

    def digest_for(shape) -> str:
        source = tmp_path / f"{shape.tables}.twb"
        source.write_bytes(workbook_xml(shape))
        out = tmp_path / f"out{shape.tables}"
        pipeline.run(source, out)
        running = hashlib.sha256()
        for path in sorted(out.rglob("*")):
            if path.is_file():
                running.update(str(path.relative_to(out)).replace("\\", "/").encode())
                running.update(path.read_bytes())
        return running.hexdigest()

    assert digest_for(TYPICAL) != digest_for(Shape(tables=6))


# --- the generator itself ----------------------------------------------------------


def test_the_generated_workbook_is_itself_deterministic():
    """Both callers depend on it. A corpus that varies makes the timing
    incomparable and the determinism proof vacuous."""
    assert workbook_xml(TYPICAL) == workbook_xml(TYPICAL)


def test_the_generated_workbook_is_the_shape_it_claims():
    """The counts are used in failure messages, so they have to be true."""
    result_xml = workbook_xml(TYPICAL).decode("utf-8")
    assert result_xml.count("<datasource ") == TYPICAL.tables
    assert result_xml.count("<worksheet ") == TYPICAL.worksheets
    assert result_xml.count("<calculation ") == TYPICAL.calculations
