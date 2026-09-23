"""The PBIR schema versions Power BI Desktop will actually accept.

`version.json` got the project open. It then failed to *render*:

    An error occurred while rendering the report.
    TypeError: Cannot read properties of undefined (reading 'visualContainers')
      at DesktopExplorationComponent.onExplorationActivated

That is a better failure than the last one - the semantic model loaded, five
tables and all their columns, `Model Default Mode: Import` - and it is still a
failure, caused by two schema versions this project declares that Desktop does
not support.

## Where these numbers come from

Not from documentation and not from inference. Power BI Desktop ships its own
map of which schema versions it accepts, in
`bin/WebView2Resources/minerva/scripts/desktop.min.js`, keyed by artifact:

    report:              {"0.0.0":!1,"1.0.0":!0,...,"1.3.0":!0,
                          "2.0.0":e.featureSwitches.pbir_report_2_0_0, ...}
    visualConfiguration: {"0.0.0":!1,"1.0.0":!1,"1.1.0":!1,"1.2.0":!1,"1.3.0":!1,
                          "1.4.0":!0,"1.5.0":!0,"1.6.0":!0,"1.7.0":!0, ...}
    visualContainer:     {"0.0.0":!1,"1.0.0":!0,...,"1.7.0":!0,"2.0.0":!0, ...}
    page:                {"0.0.0":!1,"1.0.0":!0,...,"1.4.0":!0,
                          "1.5.0":e.featureSwitches.pbi_consumption_2025_06, ...}

`!0` is `true` and `!1` is `false`. Every `pbir_*` feature switch in this build
is declared `null`, so **polarity decides the answer**: `switch` is falsy and
refuses the version, while `!switch` is truthy and accepts it. `report/2.0.0`
and `page/2.0.0` are the first kind; `report/3.1.0` and `page/2.1.0` the second.

Only unconditional `!0` entries are listed in `SUPPORTED` below. That is
narrower than the map - several `!switch` versions evaluate true today - and
deliberately so: a switch that flips in a later build changes the answer, and
this project would rather emit an older version everywhere than a newer one
that works on the machine it was built on.

The misreading worth recording: the `1.0.0`-through-`1.3.0` refusals above
belong to **`visualConfiguration`**, not to `visualContainer`, and they were
attributed to the wrong artifact here at first. It made no difference to what is
emitted - `1.4.0` is accepted by both - but it did credit the render failure to
the wrong cause. The actual cause, found later by an A/B bisect against Desktop,
was five visuals written with an empty `queryState`; see
`tests/test_pbir_empty_visuals.py`.

`pagesMetadata/1.0.0` and `versionMetadata/1.0.0` are `!0` and were correct as
they stood - worth stating, because the first hypothesis here was that *every*
declared version was wrong, and checking the map disproved it before any of them
were changed.

## Why this is a test and not a constant with a comment

These numbers are a claim about someone else's product. They will go stale when
Desktop changes, and the failure when they do is a rendering error with a
JavaScript stack trace - a long way from the line that caused it. Naming them
here means the next person reads the reason rather than rediscovering it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engines.t2pbi import pipeline

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: Verified against Power BI Desktop 2.157.879.0's own version map. A version is
#: listed here only if the map gives it an unconditional `!0`; anything guarded
#: by a feature switch is excluded, because every switch in this build is null.
SUPPORTED = {
    "report": {"1.0.0", "1.1.0", "1.2.0", "1.3.0"},
    "visualContainer": {"1.4.0", "1.5.0", "1.6.0", "1.7.0", "2.0.0", "2.2.0", "2.4.0"},
    "page": {"1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0"},
    "pagesMetadata": {"1.0.0"},
    "versionMetadata": {"1.0.0"},
}


@pytest.fixture(scope="module")
def definition(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("pbip")
    result = pipeline.run(FIXTURES / "clashes.twb", out)
    project = Path(result.pbip_path)
    root = project.parent if project.is_file() else project
    return next(root.glob("*.Report/definition"))


def _declared(path: Path) -> tuple[str, str]:
    """`(artifact, version)` from a file's `$schema`."""
    schema = json.loads(path.read_text("utf-8"))["$schema"]
    parts = schema.rstrip("/schema.json").split("/")
    return parts[-2], parts[-1]


def _every_json(definition: Path) -> list[Path]:
    return sorted(p for p in definition.rglob("*.json"))


def test_every_declared_schema_version_is_one_desktop_accepts(definition):
    """The whole point. One assertion over every file the emitter writes."""
    rejected: list[str] = []
    for path in _every_json(definition):
        artifact, version = _declared(path)
        allowed = SUPPORTED.get(artifact)
        if allowed is None:
            rejected.append(f"{path.name}: unknown artifact {artifact!r}")
        elif version not in allowed:
            rejected.append(
                f"{path.relative_to(definition)}: {artifact}/{version} is not in "
                f"{sorted(allowed)}"
            )
    assert rejected == [], rejected


def test_the_report_is_not_declared_at_a_feature_switched_version(definition):
    """`report/2.0.0` is guarded by `pbir_report_2_0_0`, which is null here.

    Declaring a version behind a switch means the project renders on whichever
    machines happen to have the switch on, which is worse than not rendering
    anywhere: it works for the developer and not for the customer.
    """
    artifact, version = _declared(definition / "report.json")
    assert artifact == "report"
    assert version != "2.0.0"


def test_a_visual_is_not_declared_at_a_version_desktop_refuses(definition):
    """Stay at or above `1.4.0`, the floor of the *stricter* of the two maps.

    `visualContainer` itself accepts 1.0.0 upward, but the sibling
    `visualConfiguration` map refuses everything below 1.4.0 - and a visual's
    config is deserialized from the same file. Declaring the container at a
    version whose configuration schema is refused is a visual that does not
    deserialize, and a page left with no `visualContainers` for the renderer to
    read.
    """
    visuals = list(definition.glob("pages/*/visuals/*/visual.json"))
    assert visuals, "no visuals were written at all"
    for path in visuals:
        artifact, version = _declared(path)
        assert artifact == "visualContainer"
        assert version not in {"1.0.0", "1.1.0", "1.2.0", "1.3.0"}, path


def test_the_versions_that_were_already_right_are_left_alone(definition):
    """The first hypothesis was that every declared version was wrong.

    Desktop's map disproved it before anything was changed. Keeping that here
    stops a future change from "fixing" files that were never broken.
    """
    assert _declared(definition / "pages" / "pages.json") == ("pagesMetadata", "1.0.0")
    assert _declared(definition / "version.json") == ("versionMetadata", "1.0.0")


def test_pages_are_declared_at_the_version_whose_shape_they_are_written_in(
    definition,
):
    """Back to `1.0.0`, and the reasoning that moved it to `1.4.0` was backwards.

    The argument was that a page carrying `filterConfig` - a property the
    `pbir_filterConfiguration_1_3_0` switch dates to 1.3.0 - should not declare
    1.0.0, because that describes the file as something it is not.

    What that missed is what the declared version is *for*. Desktop picks a
    chain of **upgrader** services from it: a page that says 1.0.0 is normalised
    forward to the shape the current build wants, and one that says 1.4.0 is
    taken at its word as already being that shape. This emitter writes the
    1.0.0 shape. Claiming 1.4.0 did not make the file more accurate - it skipped
    the code that would have made the claim true, and Power BI Desktop stopped
    rendering the report on 2026-09-05 with the `visualContainers` TypeError a
    page that fails to deserialize produces.

    The version map is also not the gate it looks like.
    `VersioningUtils.isVersionEnabledForOpen` consults it only for versions of
    the form `X.0.0`; anything with a non-zero minor or patch is accepted
    regardless. 1.4.0 was never refused. It was accepted and then read as a
    shape it was not.
    """
    pages = list((definition / "pages").glob("*/page.json"))
    assert pages
    for page in pages:
        assert _declared(page) == ("page", "1.0.0")
