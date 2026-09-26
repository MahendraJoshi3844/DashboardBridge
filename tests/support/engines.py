"""Skips for tests that need an engine the deployment may not have.

Every engine is a separate product and an optional install, so the shell's suite
runs in two shapes: with all engines (the full CI job) and with none (the
core-only job). A test that drives a real conversion needs the engine it drives;
it says so with one of these rather than failing where that engine was not
bought. Anything that does not need an engine must pass in both shapes.
"""

from __future__ import annotations

from importlib.util import find_spec

import pytest


def needs(module: str, product: str) -> pytest.MarkDecorator:
    return pytest.mark.skipif(
        find_spec(module) is None,
        reason=f"the {product} engine ({module}) is not installed on this deployment",
    )


#: Tableau <-> Power BI (both directions are the Tableau product).
needs_tableau = needs("t2pbi", "Tableau")
