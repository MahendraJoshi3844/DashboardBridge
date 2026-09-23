"""Everything the engine declares it needs must actually be installed by CI.

CI does not install the engine's package. It installs
`apps/api/requirements.txt` and then a hand-written list of engine
dependencies, which means `pyproject.toml` can grow a dependency that CI never
installs and nobody finds out until an import fails on a clean machine.

That already happened once. `P3.1` moved the DAX rules into YAML and added
`pyyaml` to `pyproject.toml`; CI installed neither, and the suite passed anyway
because `uvicorn[standard]` happens to pull PyYAML in as an extra. An API
server's optional extra was satisfying an engine dependency by accident, and
would have stopped the day uvicorn dropped it.

So this compares the declaration against what CI installs, rather than trusting
the two to be kept in step by hand.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Declared because the desktop shell needs it, imported lazily so the headless
#: suite never touches it. CI deliberately leaves it out.
DESKTOP_ONLY = {"pywebview"}


def _declared() -> set[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    names = {
        re.split(r"[<>=!\[; ]", dep, maxsplit=1)[0].strip().lower()
        for dep in config["project"]["dependencies"]
    }
    return names - DESKTOP_ONLY


def _installed_by_ci() -> str:
    """Everything CI's Python job could install, as one blob to search.

    Deliberately textual. Parsing the workflow's shell into a package list would
    be a second implementation of pip's command line, and the question here is
    only "is this name anywhere in what CI installs".
    """
    return "\n".join(
        (
            (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
            (ROOT / "apps" / "api" / "requirements.txt").read_text(encoding="utf-8"),
        )
    ).lower()


def test_ci_installs_every_dependency_the_engine_declares():
    blob = _installed_by_ci()
    missing = sorted(name for name in _declared() if name not in blob)
    assert not missing, (
        f"{', '.join(missing)} is declared in pyproject.toml but appears "
        "nowhere in what CI installs. The suite may still pass by accident, "
        "on a transitive dependency of something else."
    )


def test_the_desktop_only_dependency_is_still_the_only_exemption():
    """If the exemption list grows, it should be a decision, not a drift."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {
        re.split(r"[<>=!\[; ]", dep, maxsplit=1)[0].strip().lower()
        for dep in config["project"]["dependencies"]
    }
    assert DESKTOP_ONLY <= declared, (
        "the exemption names a package pyproject no longer declares"
    )


# --- the other place code gets installed ------------------------------------

#: Every root an import in this repo resolves from. `engines` is a top-level
#: package at the repo root and the converter lives under it since `P2.1`;
#: `app` under `apps/api`; the contracts under their own `src`.
IMPORT_ROOTS = ("/workspace", "/workspace/apps/api",
                "/workspace/packages/contracts/src")


def _compose() -> str:
    return (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def test_the_api_container_can_import_every_package_it_runs():
    """`docker compose up` has to produce a working API, not a starting one.

    This was found the hard way: the compose PYTHONPATH named two of the four
    roots, so the container could not import `app.main` at all - it failed at
    startup, and `P0.6` had been ticked on the strength of the file existing
    rather than the stack running.
    """
    compose = _compose()
    line = next(
        (row for row in compose.splitlines() if row.strip().startswith("PYTHONPATH:")),
        "",
    )
    assert line, "docker-compose.yml sets no PYTHONPATH"
    missing = [root for root in IMPORT_ROOTS if root not in line]
    assert not missing, (
        f"the api container's PYTHONPATH omits {missing}, so it cannot import "
        "the packages it runs"
    )


def test_the_api_container_installs_the_engine_dependencies_too():
    """The container installs requirements.txt and nothing else.

    So requirements.txt - not CI's hand-written list - is what has to carry
    every runtime dependency. lxml was missing from it, which meant a
    containerised API could not parse a workbook.
    """
    requirements = (ROOT / "apps" / "api" / "requirements.txt").read_text(
        encoding="utf-8"
    ).lower()
    missing = sorted(name for name in _declared() if name not in requirements)
    assert not missing, (
        f"{', '.join(missing)} is declared in pyproject.toml but not in "
        "apps/api/requirements.txt, which is all the API container installs."
    )
