"""The files Power BI Desktop requires before it will open a report (`P3` acceptance).

**This file exists because Desktop finally ran.** Every other test here reasons
about the PBIR format from documentation and from a hand-authored fixture. On
2026-09-04 a generated project was opened in Power BI Desktop 2.157.879.0 for the
first time, and it refused:

    Cannot find file 'version.json'.
      at ExplorationSerializer.GetFileData(files, fileName, folderPath, isRequired)
      at ExplorationSerializer.DeserializeRootExplorationArtifactAsync(...)
    Error Reading StorageSection: ReportDocument

Nothing in this repository had noticed, and nothing could have: the emitter, its
snapshot tests and the hand-authored PBIP fixture were all written from the same
incomplete understanding of the format, so they agreed with each other. A reader
checked only against its own writer agrees with itself and can still open
nothing real - the same trap `P6a.1` was written to avoid on the other side, and
it caught us here on this one.

## What this asserts, and how sure it is

The *presence* of `definition/version.json` is certain: Desktop named the file,
the folder it looked in, and the fact that it is required.

The *content* is inferred - from the schema list Power BI Desktop ships in
`bin/WebView2Resources/minerva`, which includes
`versionMetadata/1.0.0/schema.json`, and from the `"version": "4.0"` that
`definition.pbir` already carries and Desktop already accepts. It is not
confirmed by a saved-from-Desktop project, because there is no real one on this
machine to compare against. That is the next piece of evidence to get, and until
it exists these assertions are the best available reasoning rather than proof.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engines.t2pbi import pipeline

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def report_definition(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("pbip")
    result = pipeline.run(FIXTURES / "clashes.twb", out)
    project = Path(result.pbip_path)
    root = project.parent if project.is_file() else project
    definitions = list(root.glob("*.Report/definition"))
    assert definitions, f"no report definition folder under {root}"
    return definitions[0]


# --- what Desktop asked for by name -----------------------------------------------


def test_version_json_exists(report_definition):
    assert (report_definition / "version.json").is_file(), (
        "Power BI Desktop refuses the whole project without this: "
        "\"Cannot find file 'version.json'\""
    )


def test_version_json_is_readable_json_with_a_version(report_definition):
    content = json.loads((report_definition / "version.json").read_text("utf-8"))
    assert content.get("version"), content


def test_version_json_declares_the_schema_desktop_ships(report_definition):
    """`versionMetadata/1.0.0/schema.json` is in Desktop's own schema list."""
    content = json.loads((report_definition / "version.json").read_text("utf-8"))
    assert content["$schema"].endswith("versionMetadata/1.0.0/schema.json")


def test_the_version_agrees_with_the_one_definition_pbir_already_declares(
    report_definition,
):
    """Two files stating a version, and Desktop reads both.

    `definition.pbir` says `4.0` and Desktop accepted that far enough to reach
    the report definition. Stating a different number in the file beside it
    would be this project inventing a disagreement.
    """
    version = json.loads((report_definition / "version.json").read_text("utf-8"))
    pbir = json.loads(
        (report_definition.parent / "definition.pbir").read_text("utf-8")
    )
    assert version["version"] == pbir["version"]


# --- the rest of what a report definition must contain ------------------------------


@pytest.mark.parametrize(
    "relative",
    ["version.json", "report.json", "pages/pages.json"],
    ids=["version", "report", "pages-metadata"],
)
def test_every_required_report_file_is_present(report_definition, relative):
    """One list, so a future omission fails by name rather than in Desktop."""
    assert (report_definition / relative).is_file(), f"{relative} was not written"


def test_every_page_folder_has_a_page_file(report_definition):
    for page in (report_definition / "pages").iterdir():
        if page.is_dir():
            assert (page / "page.json").is_file(), f"{page.name} has no page.json"


def test_the_hand_authored_fixture_has_the_same_required_files():
    """The fixture mimics a Desktop-saved project, and it was missing this too.

    It was authored from the same understanding as the emitter, which is exactly
    why neither noticed. Keeping them in step here means the reader is tested
    against a project shaped like one Desktop would accept.
    """
    definition = FIXTURES / "pbip" / "Retail.Report" / "definition"
    assert (definition / "version.json").is_file()
