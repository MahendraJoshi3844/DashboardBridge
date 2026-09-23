"""The layering invariant, checked rather than remembered.

`CLAUDE.md` and the technical design both state it: **`engines/` imports
`t2pbi`, never the reverse**, and `packages/contracts` depends on nothing. It is
the reason `P3.1` kept the DAX rule pack inside the engine package, and the
reason the canonical model is the only thing that crosses between adapters.

Nothing was checking it. An invariant that lives only in a document is one that
holds until the first person who has not read the document adds an import, and
the code keeps working, the tests keep passing, and the property is gone.

This was written because a change broke it: `P7.8` made `engines/t2pbi/
assist.py` call `require_loopback` from `engines/ai/provider.py` - the right
check in the wrong direction. It is exempted below with a reason and a companion
test, on the same terms as `LEGACY_MODEL_CALLERS`, rather than quietly allowed.

A grep over imports is a blunt instrument. It is also the only thing that
notices an import nobody meant to add.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engines" / "t2pbi"
CONTRACTS = ROOT / "packages" / "contracts" / "src"

#: The sibling packages the converter must not reach into. `engines.t2pbi` is
#: itself under `engines/`, so the rule is about these specific neighbours
#: rather than about the directory name.
SIBLINGS = ("engines.ai", "engines.adapters", "engines.conversion", "engines.validation")

#: What `engines/t2pbi` may reach up into, and why.
#:
#: `assist.py` is the pywebview desktop shell's local model assist, already the
#: single named exception in `test_ai_boundaries.py`. `P7.8` gave it the
#: loopback check that the rest of the AI layer uses, because the alternative -
#: a second implementation of the same security check - is how one of them gets
#: fixed and the other does not. It retires with the shell once ADR-006 settles.
ALLOWED_UPWARD = {
    (Path("engines") / "t2pbi" / "assist.py", "engines.ai.provider"),
}


def _imports(path: Path) -> set[str]:
    """Every module a file imports, including inside a function body."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            found.add(node.module or "")
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def _python_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def test_the_engine_never_imports_a_sibling_engine():
    """The direction that makes the IR a seam rather than a suggestion.

    If the converter may reach into `engines/adapters`, "read Tableau" can touch
    "write Power BI" without either of them going through the IR - and the whole
    reason the IR exists is that the two stay apart.
    """
    offenders: list[str] = []
    for path in _python_files(ENGINE):
        relative = path.relative_to(ROOT)
        for module in _imports(path):
            if not module.startswith(SIBLINGS):
                continue
            if any(
                relative == allowed and module.startswith(prefix)
                for allowed, prefix in ALLOWED_UPWARD
            ):
                continue
            offenders.append(f"{relative} imports {module}")

    assert offenders == [], (
        f"{offenders} import upward. `engines/` imports `t2pbi`, never the "
        "reverse. Move what is needed down, or add it to ALLOWED_UPWARD with a "
        "reason."
    )


def test_every_upward_exemption_is_still_real():
    """An exemption list that outlives what it exempted stops meaning anything.

    Both halves are checked: the file still exists, and it still has the import
    the exemption was written for. A stale entry is worse than none, because it
    reads as a considered decision.
    """
    for relative, module in ALLOWED_UPWARD:
        path = ROOT / relative
        assert path.exists(), (
            f"{relative} is gone; remove it from ALLOWED_UPWARD so the list "
            "keeps meaning something"
        )
        assert any(name.startswith(module) for name in _imports(path)), (
            f"{relative} no longer imports {module}; remove the exemption"
        )


def test_the_contracts_package_depends_on_nothing_of_ours():
    """It is imported by every layer, so anything it imported would be too.

    A contract that reached back into the engine would make the engine a
    dependency of the web app's generated types, which is how a "shared" package
    becomes the thing nobody can change.
    """
    ours = ("engines", "app.", "apps.", "dashboardbridge_contracts.")
    offenders: list[str] = []
    for path in _python_files(CONTRACTS):
        for module in _imports(path):
            if module.startswith(ours) and not module.startswith(
                "dashboardbridge_contracts."
            ):
                offenders.append(f"{path.relative_to(ROOT)} imports {module}")

    assert offenders == [], f"{offenders}: contracts must depend on nothing of ours"
