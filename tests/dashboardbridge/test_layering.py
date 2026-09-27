"""The layering invariants, checked rather than remembered.

DashboardBridge is the shell over separately sold engines - `t2pbi` (Tableau),
`mstr2pbi` (MicroStrategy), `qlik2pbi` (Qlik) - each in its own repository and
each optional. Two things keep that true:

* **Engines are reached only through their seams.** A module-level engine import
  anywhere else makes the whole shell fail to start on a deployment that did
  not buy that engine. The seams are imported lazily, after `directions` has
  said the engine is installed. (That an engine never imports the shell is
  checked in the engine's own repository, where the engine lives.)
* `packages/contracts` depends on nothing of ours.

A grep over imports is a blunt instrument. It is also the only thing that
notices an import nobody meant to add.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "packages" / "contracts" / "src"
SHELL = (ROOT / "engines", ROOT / "apps" / "api" / "app")

#: The engines, each a separate product and an optional install.
ENGINES = ("t2pbi", "mstr2pbi", "qlik2pbi")

#: The only modules that may import an engine at module level. Everything else
#: imports them inside a function, after the engine is known to be installed.
SEAMS = {
    Path("engines/adapters/tableau.py"),
    Path("engines/conversion/run.py"),
    Path("engines/conversion/from_microstrategy.py"),
    Path("engines/conversion/from_qlik.py"),
}


def _imports(path: Path) -> set[str]:
    """Every module a file imports, including inside a function body."""
    return _collect(ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))))


def _top_level_imports(path: Path) -> set[str]:
    """What a file imports when it is itself imported (not inside a function)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes = []
    pending = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        nodes.append(node)
        pending.extend(ast.iter_child_nodes(node))
    return _collect(nodes)


def _collect(nodes) -> set[str]:
    found: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            found.add(node.module or "")
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def _python_files(*roots: Path) -> list[Path]:
    return [
        path
        for root in roots
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _is_engine(module: str) -> bool:
    return module.split(".")[0] in ENGINES


def test_engines_are_imported_at_module_level_only_by_their_seams():
    """A shell that imports an engine eagerly cannot start without it.

    A Qlik-only customer's deployment has no `t2pbi`; if `app.api.analysis`
    imported it at the top, the API would not even boot there.
    """
    offenders = [
        f"{path.relative_to(ROOT)} imports {module}"
        for path in _python_files(*SHELL)
        if path.relative_to(ROOT) not in SEAMS
        for module in _top_level_imports(path)
        if _is_engine(module)
    ]
    assert offenders == [], (
        f"{offenders}: import the engine inside the function that needs it, or "
        "go through its seam in engines/conversion"
    )


def test_every_seam_still_imports_its_engine():
    """A seam list that outlives what it listed stops meaning anything."""
    for relative in SEAMS:
        path = ROOT / relative
        assert path.exists(), f"{relative} is gone; remove it from SEAMS"
        assert any(_is_engine(m) for m in _top_level_imports(path)), (
            f"{relative} no longer imports an engine; remove it from SEAMS"
        )


def test_the_shell_does_not_vendor_an_engine():
    """The engines live in their own repositories; a copy here would drift."""
    for engine in ENGINES:
        assert not (ROOT / engine).exists(), f"{engine}/ belongs in its own repository"


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
