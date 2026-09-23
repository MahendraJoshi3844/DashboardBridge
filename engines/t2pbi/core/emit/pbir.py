"""Emit PBIR report files (pages + visuals) from mapped Power BI visuals.

PBIR is text/JSON. Exact schema fidelity is confirmed by opening in Power BI Desktop;
we generate documented-shape structure deterministically. See docs/specs/modules/visual.md.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from engines.t2pbi.core.emit.filters import filter_config
from engines.t2pbi.core.emit.tmdl import sanitize_name
from engines.t2pbi.core.mapping import FieldRef, PBIVisual

_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"

# Per-visual-type well names; default chart wells, table uses a single Values well.
_WELLS = {
    "tableEx": ("Values", "Values", "Values"),
    "card": ("Values", "Values", "Values"),
}
_DEFAULT_WELLS = ("Category", "Y", "Series")  # (category, values, legend)


def _short_id(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]


def _write(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8", newline="\n")


def _projection(ref: FieldRef) -> dict:
    return {
        "field": {
            "Column": {
                "Expression": {"SourceRef": {"Entity": sanitize_name(ref.table)}},
                "Property": ref.column,
            }
        },
        "queryRef": f"{sanitize_name(ref.table)}.{ref.column}",
        "nativeQueryRef": ref.column,
    }




def writable(visual: PBIVisual) -> bool:
    """Can a visual be written for this worksheet at all?

    One rule, and it lives on `PBIVisual` rather than here. The mapping stage
    has to know the same answer - it writes the flag that says whether a visual
    was produced - and the first version of this fix asked the question twice,
    in two places, in two different ways. That is the shape of the bug it was
    fixing: a flag claiming "Visual generated as 'clusteredBarChart'" beside a
    container with no field on it.

    `tests/test_pbir_empty_visuals.py` is the backstop. It asserts that nothing
    on disk has an empty `queryState`, so if this ever answers `True` for a
    visual that turns out to have no projections, a test says so rather than
    Power BI Desktop.
    """
    return visual.unwritable_because() is None


def _query_state(visual: PBIVisual) -> dict:
    cat_well, val_well, leg_well = _WELLS.get(visual.visual_type, _DEFAULT_WELLS)
    state: dict[str, dict] = {}

    def add(well: str, refs: list[FieldRef]) -> None:
        if not refs:
            return
        projs = [_projection(r) for r in refs]
        state.setdefault(well, {"projections": []})["projections"].extend(projs)

    add(cat_well, visual.category)
    add(val_well, visual.values)
    add(leg_well, visual.legend)
    return state


#: The report definition format version. It is stated twice - here and in
#: `definition.pbir` - because Power BI Desktop reads both, so they are derived
#: from one constant rather than written out twice and allowed to drift.
DEFINITION_VERSION = "4.0"

#: The `page` schema version to write.
#:
#: **1.0.0, and the reasoning that moved it to 1.4.0 was backwards.** Desktop
#: runs a chain of *upgrader* services per artifact, chosen by the declared
#: version: a file that says 1.0.0 is normalised forward, and a file that says
#: 1.4.0 is taken at its word as already being in that shape. This emitter
#: writes the 1.0.0 shape. Labelling it 1.4.0 did not describe the file more
#: accurately, it skipped the code that would have made the claim true - and
#: Power BI Desktop stopped rendering the report on 2026-09-05, with the same
#: `Cannot read properties of undefined (reading 'visualContainers')` that a
#: page which fails to deserialize produces.
#:
#: The version map is not the whole story either. `VersioningUtils
#: .isVersionEnabledForOpen` only consults it for versions of the form `X.0.0`;
#: anything with a non-zero minor or patch is accepted regardless. So 1.4.0 was
#: never *refused* - it was accepted and then read as a shape it was not.
PAGE_VERSION = "1.0.0"


def write_report_definition(
    visuals: list[PBIVisual], report_dir: Path, *, emit_filters: bool = False
) -> None:
    """Write the PBIR definition.

    `emit_filters` is **off by default and that is a statement about evidence,
    not about the code**. The `filterConfig` block is built from Desktop's own
    serializer and every part of its shape is tested, but no Power BI Desktop
    has yet opened a project containing one - and the first that tried failed to
    render. Until a Desktop says otherwise, writing it would be exactly the
    guess this converter refuses to make everywhere else; the conversion is
    reported as manual work instead, with the filter's values named.

    Turn it on to produce a project to test with. Turn it on by default when a
    Desktop has opened one.
    """
    definition = report_dir / "definition"

    # version.json. Power BI Desktop refuses the *entire project* without this,
    # with "Cannot find file 'version.json'" out of ExplorationSerializer -
    # not a degraded report, a project that does not open. Found on 2026-09-04,
    # the first time a generated project was opened in Desktop; nothing here
    # had noticed, because the emitter, its tests and the hand-authored fixture
    # were all written from the same incomplete reading of the format and so
    # agreed with each other.
    _write(
        definition / "version.json",
        {
            "$schema": f"{_SCHEMA}/versionMetadata/1.0.0/schema.json",
            "version": DEFINITION_VERSION,
        },
    )

    # report.json
    # `report/2.0.0` is guarded by the `pbir_report_2_0_0` feature switch,
    # which is null in shipping Desktop - so it is refused. `1.3.0` is the
    # highest version Desktop accepts unconditionally. See
    # tests/test_pbir_schema_versions.py for where these numbers come from.
    _write(
        definition / "report.json",
        {"$schema": f"{_SCHEMA}/report/1.3.0/schema.json"},
    )

    # One page per visual (worksheet). Deterministic ids + grid positions.
    page_ids: list[str] = []
    for i, visual in enumerate(visuals):
        page_id = _short_id("page:" + visual.name)
        page_ids.append(page_id)
        page_dir = definition / "pages" / page_id

        # A Tableau worksheet filter applies to the whole worksheet, and each
        # worksheet becomes one page here - so the page is where it belongs.
        # Desktop's `PageSerializer.serializePage` puts `filterConfig` on the
        # page's own content, beside `displayOption` and `height`.
        page = {
            "$schema": f"{_SCHEMA}/page/{PAGE_VERSION}/schema.json",
            "name": page_id,
            "displayName": visual.name,
            "displayOption": "FitToPage",
            "height": 720,
            "width": 1280,
        }
        if emit_filters:
            carried = filter_config(visual.name, visual.filters)
            if carried is not None:
                page["filterConfig"] = carried
        _write(page_dir / "page.json", page)

        if not writable(visual):
            # The page stays: the worksheet existed, and an empty page beside a
            # flag saying why is a smaller loss than a page that is not there.
            continue

        visual_id = _short_id("visual:" + visual.name)
        _write(
            page_dir / "visuals" / visual_id / "visual.json",
            {
                # Desktop's map has visualContainer 1.0.0 through 1.3.0 as
                # `!1` - explicitly refused. 1.4.0 is the lowest it accepts,
                # and the closest to the shape written here.
                "$schema": f"{_SCHEMA}/visualContainer/1.4.0/schema.json",
                "name": visual_id,
                "position": {"x": 16, "y": 16, "z": 0, "width": 1248, "height": 688, "tabOrder": 0},
                "visual": {
                    "visualType": visual.visual_type,
                    "query": {"queryState": _query_state(visual)},
                    "drillFilterOtherVisuals": True,
                },
            },
        )

    if not page_ids:
        # Valid report still needs one page.
        page_id = _short_id("page:__empty__")
        page_ids.append(page_id)
        _write(
            definition / "pages" / page_id / "page.json",
            {
                "$schema": f"{_SCHEMA}/page/{PAGE_VERSION}/schema.json",
                "name": page_id,
                "displayName": "Page 1",
                "displayOption": "FitToPage",
                "height": 720,
                "width": 1280,
            },
        )

    _write(
        definition / "pages" / "pages.json",
        {
            "$schema": f"{_SCHEMA}/pagesMetadata/1.0.0/schema.json",
            "pageOrder": page_ids,
            "activePageName": page_ids[0],
        },
    )
