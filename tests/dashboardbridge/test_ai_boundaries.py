"""Two boundaries `P4.1` draws, checked against the source rather than trusted.

Both are stated in 07-ai-engine.md and neither is visible when it erodes: the
code keeps working, the tests keep passing, and the property the product sells
is quietly gone. A grep is a blunt instrument, but it is the only thing that
notices an import nobody meant to add.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AI = ROOT / "engines" / "ai"

#: Everywhere a conversion happens. None of it may name a provider.
CONSUMERS = (
    ROOT / "engines" / "t2pbi",
    ROOT / "engines" / "conversion",
    ROOT / "engines" / "adapters",
    ROOT / "engines" / "validation",
    ROOT / "apps" / "api" / "app",
)

CONCRETE_PROVIDERS = {"OllamaProvider", "OpenAICompatibleProvider", "MockProvider"}

#: Types that carry a workbook, or enough of one to matter.
WORKBOOK_TYPES = {"Workbook", "CanonicalModel", "DataSource", "Table"}


def _imports(path: Path) -> list[tuple[str, str]]:
    """Every `(module, name)` a file imports. `name` is "" for a plain import."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            found.extend((module, alias.name) for alias in node.names)
        elif isinstance(node, ast.Import):
            found.extend((alias.name, "") for alias in node.names)
    return found


def _python_files(*roots: Path) -> list[Path]:
    return [
        path
        for root in roots
        if root.exists()
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def test_conversion_code_never_names_a_provider():
    """§26: "Conversion code never imports a vendor."

    Everything above this layer depends on the `LLMProvider` protocol, so
    adding Azure OpenAI or Anthropic later is a new class in `engines/ai` and no
    change anywhere else. One direct import of a concrete provider is all it
    takes for that to stop being true, and it would never fail a test.
    """
    offenders = [
        f"{path.relative_to(ROOT)} imports {name}"
        for path in _python_files(*CONSUMERS)
        for module, name in _imports(path)
        if name in CONCRETE_PROVIDERS or module.startswith("engines.ai.providers")
    ]
    assert offenders == [], offenders


def test_the_ai_layer_cannot_be_handed_a_workbook():
    """Data minimisation (§29) as an architectural fact, not a discipline.

    `LLMRequest` has nowhere to put a workbook. This is the other half: the AI
    layer does not import the types that hold one, so no future function here
    can take one as a parameter without the import that would fail this test.
    """
    offenders = [
        f"{path.relative_to(ROOT)} imports {name or module}"
        for path in _python_files(AI)
        for module, name in _imports(path)
        if name in WORKBOOK_TYPES
        or module.startswith("engines.t2pbi.ir")
        or module.endswith("canonical")
    ]
    assert offenders == [], offenders



#: Classes whose `.generate()` is not a model call. The guard looks for the
#: *word*, which is blunt on purpose - but `Ed25519PrivateKey.generate()` in
#: `engines/licensing` is a keypair, not a completion, and excluding the whole
#: module would let a real provider call hide there later. Naming the receiver
#: keeps the guard pointed at `provider.generate(...)`, which is what it is for.
_NOT_A_PROVIDER = {"Ed25519PrivateKey", "Ed25519PublicKey", "rsa", "ec"}


def _is_not_a_provider(called: ast.Attribute) -> bool:
    value = called.value
    return isinstance(value, ast.Name) and value.id in _NOT_A_PROVIDER


def test_only_the_router_asks_a_provider_for_anything():
    """07-ai-engine.md: "The router is the only entry point."

    That sentence is the reason there is exactly one place where "should this
    reach a model?" is answered - which is also the only place the offline
    guarantee, the privacy mode and the no-fallback rule can be enforced. A
    second caller anywhere would not fail a test, would not look wrong in
    review, and would bypass all three.
    """
    allowed = {AI / "router.py", AI / "providers.py"}
    offenders = []
    for path in _python_files(ROOT / "engines", ROOT / "apps" / "api" / "app"):
        if path in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            called = getattr(node, "func", None)
            if isinstance(node, ast.Call) and isinstance(called, ast.Attribute):
                if called.attr == "generate" and not _is_not_a_provider(called):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == [], offenders


#: The one module outside `engines/ai` that talks to a model runtime directly.
#: It predates the router: it is the pywebview desktop shell's local assist, and
#: it opens its own socket rather than calling a provider, so the check above
#: cannot see it. Named here so the exception is a decision on the record rather
#: than a gap nobody noticed. It retires into the router once ADR-006 settles
#: whether the desktop shell survives at all.
LEGACY_MODEL_CALLERS = {Path("engines") / "t2pbi" / "assist.py"}

#: How a model runtime is reached without going near a provider class.
_RUNTIME_MARKERS = ("11434", "/api/generate", "/chat/completions")


def test_no_new_module_reaches_a_model_runtime_behind_the_router():
    """The other way to bypass the router: open the socket yourself.

    `test_only_the_router_asks_a_provider_for_anything` watches for calls to a
    provider. Nothing stops a module skipping providers entirely and speaking
    HTTP to the runtime, which is exactly what the legacy desktop assist does -
    so that check alone would have let a second one in without a word.
    """
    offenders = []
    for path in _python_files(ROOT / "engines", ROOT / "apps" / "api" / "app"):
        if AI in path.parents or path.relative_to(ROOT) in LEGACY_MODEL_CALLERS:
            continue
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in _RUNTIME_MARKERS):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], (
        f"{offenders} reaches a model runtime without going through the router. "
        "Route it, or add it to LEGACY_MODEL_CALLERS with a reason."
    )


def test_the_legacy_exception_still_exists():
    """If the desktop assist is retired, this list should shrink with it."""
    for relative in LEGACY_MODEL_CALLERS:
        assert (ROOT / relative).exists(), (
            f"{relative} is gone; remove it from LEGACY_MODEL_CALLERS so the "
            "exemption list keeps meaning something"
        )
