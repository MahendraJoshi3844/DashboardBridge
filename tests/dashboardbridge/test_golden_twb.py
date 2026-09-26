"""Golden `.twb` output (`P6b.3`).

A golden file is the whole generated workbook, checked in, compared byte for
byte. Its value is that a change to the writer shows up as a **diff a person can
read** rather than as a test name, and that the exact bytes this project claims
to produce are visible in the repository without running anything.

## What a golden proves, and what it does not

It proves the output has not *changed*. It does not prove the output is
*correct*, and the difference matters more here than usual: a golden that was
wrong the day it was written stays wrong forever, and every run agrees with it.
No Tableau Desktop has opened one of these, so nothing in this file is evidence
that Tableau accepts it.

So the golden is not left to speak for itself. Alongside the byte comparison,
this module asserts the specific things that were *reviewed* when the file was
first written — the shelf encoding, a translated calculation, a refused one and
its stated reason. Those are what would have to be re-reviewed if the golden
were ever regenerated, and they fail on their own if the writer changes them.

Regenerate with `pytest --update-golden`, then **read the diff** before
committing it. Accepting a golden diff without reading it converts this file
from evidence into a rubber stamp.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest
from lxml import etree

pytest.importorskip("t2pbi", reason="optional engine not installed on this deployment")

from engines.adapters.powerbi import PowerBIAdapter
from engines.adapters.tableau import TableauAdapter
from engines.adapters.tableau_emit import write_twb

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN = FIXTURES / "golden"

#: Written explicitly, because a golden compared against a CRLF checkout would
#: differ on every line for no reason a reader could act on.
LF = "\n"


def _from_tableau(name: str):
    adapter = TableauAdapter()
    return adapter.normalize(adapter.parse((FIXTURES / name).read_bytes()))


def _from_powerbi():
    return PowerBIAdapter().read(FIXTURES / "pbip")


def _produce(model) -> str:
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        return write_twb(model, scratch).read_text(encoding="utf-8")


def _check(name: str, produced: str, update: bool) -> None:
    """Compare a generated workbook with its golden, or rewrite it.

    Called from a *test* rather than from the fixture that builds the model: a
    `pytest.fail` inside a fixture is reported as an error against every test
    that requested it, which buries the diff under a stack of unrelated names.
    """
    expected = GOLDEN / name
    if update:
        GOLDEN.mkdir(parents=True, exist_ok=True)
        expected.write_text(produced, encoding="utf-8", newline=LF)
        return

    assert expected.is_file(), (
        f"{expected} does not exist. Run `pytest --update-golden` to write it, "
        "then read the file before committing it."
    )
    stored = expected.read_text(encoding="utf-8")
    if stored == produced:
        return
    diff = LF.join(
        difflib.unified_diff(
            stored.splitlines(),
            produced.splitlines(),
            fromfile=f"golden/{name}",
            tofile="generated",
            lineterm="",
        )
    )
    pytest.fail(
        f"The generated workbook no longer matches {expected}."
        + LF * 2
        + diff
        + LF * 2
        + "If the change is intended, run `pytest --update-golden` and read the "
        "diff before committing it."
    )


@pytest.fixture(scope="module")
def from_tableau() -> str:
    return _produce(_from_tableau("clashes.twb"))


@pytest.fixture(scope="module")
def from_powerbi() -> str:
    return _produce(_from_powerbi())


@pytest.fixture(scope="module")
def update(request) -> bool:
    return request.config.getoption("--update-golden")


# --- the files themselves ------------------------------------------------------


def test_a_tableau_workbook_written_back_matches_its_golden(from_tableau, update):
    _check("clashes.twb", from_tableau, update)


def test_a_power_bi_project_written_as_a_workbook_matches_its_golden(
    from_powerbi, update
):
    """The direction that only exists because of `P6b.2`: nothing in this file
    could be produced before a DAX expression could become a Tableau one."""
    _check("retail.twb", from_powerbi, update)


def test_both_goldens_are_well_formed_xml(from_tableau, from_powerbi):
    for text in (from_tableau, from_powerbi):
        assert etree.fromstring(text.encode("utf-8")).tag == "workbook"


# --- what was reviewed when the goldens were written ---------------------------
#
# A golden alone freezes whatever it was given, correct or not. These are the
# specific claims that were checked by reading the generated file, restated so
# that regenerating the golden cannot quietly change them.


def test_the_golden_carries_a_shelf_reference_in_tableau_s_own_encoding(from_tableau):
    """The costliest mistake available in this direction, visible in the file."""
    root = etree.fromstring(from_tableau.encode("utf-8"))
    shelves = [
        element.text
        for element in root.findall(".//rows") + root.findall(".//cols")
        if element.text
    ]
    assert shelves
    for token in shelves:
        assert token.startswith("[federated.")
        assert token.split("].[", 1)[-1].rstrip("]").count(":") == 2


def test_the_golden_carries_a_translated_dax_calculation(from_powerbi):
    """`Total Revenue = SUM(Sales[Revenue])` becomes `SUM([Revenue])`: the table
    qualifier is gone, because each table is its own Tableau data source."""
    root = etree.fromstring(from_powerbi.encode("utf-8"))
    formulas = {
        element.get("formula") for element in root.findall(".//calculation")
    }
    assert "SUM([Revenue])" in formulas
    assert "[Revenue] * (1 - 0.05)" in formulas


def test_the_golden_records_the_calculation_it_refused_and_why(from_powerbi):
    """`Revenue per Unit` uses DIVIDE, which has no rule.

    It is absent from the workbook as a formula and present as a stated reason,
    because absent and silently absent are not the same thing.
    """
    assert "DIVIDE(" not in from_powerbi
    assert "not carried" in from_powerbi
    assert "DIVIDE" in from_powerbi


def test_no_golden_carries_a_table_qualifier_into_a_formula(from_powerbi):
    """The residual check, asserted against the artifact rather than the code."""
    root = etree.fromstring(from_powerbi.encode("utf-8"))
    for element in root.findall(".//calculation"):
        assert "Sales[" not in (element.get("formula") or "")
        assert "Store[" not in (element.get("formula") or "")


def test_the_goldens_are_stored_with_unix_line_endings():
    """A `.twb` is text and is declared so in `.gitattributes`; a CRLF golden
    would fail to match on the next machine that checked it out."""
    for name in ("clashes.twb", "retail.twb"):
        assert b"\r\n" not in (GOLDEN / name).read_bytes()
