"""Load the translation rule pack (`P3.1`).

Rules are YAML beside this module rather than Python literals, so they can be
reviewed, diffed, and eventually shipped as versioned rule packs
(06-conversion-engine.md, "Rule engine").

**They live inside the engine package, not at `engines/rules/`.** The roadmap
names that path and this is still not it. The original reason has gone: reading
them from `engines/` would once have inverted the layering, and `P2.1` has since
moved the engine to `engines/t2pbi`, so `engines/rules/` is now a sibling rather
than a layer above.

What remains is smaller but real. A rule pack is *data belonging to the engine
package* — shipped with it by `package-data`, found relative to this file, and
present wherever the package is. A sibling directory would be none of those and
would need the engine to work out where the repository root is. Hoisting it is a
decision to take on its own evidence rather than as a consequence of a move.

**A malformed pack raises.** This is the whole reason the move needs care. A
Python dict cannot lose an entry between two runs; a file can - a bad merge, a
truncated write, a duplicate id shadowing its twin - and none of those raise on
their own. A lost rule converts one formula fewer, reports it as needing a
person, and is indistinguishable from a workbook that always did. So the loader
refuses the pack instead of returning the part of it that parsed.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PACK_DIR = Path(__file__).resolve().parent


class RulePackError(RuntimeError):
    """The pack is missing, unreadable, or internally inconsistent."""


@dataclass(frozen=True)
class FunctionRule:
    """A Tableau function that becomes a DAX function by direct substitution."""

    rule_id: str
    version: int
    source_function: str
    target_function: str
    strategy: str = "deterministic"
    confidence: float = 1.0
    note: str = ""


@dataclass(frozen=True)
class RefusalRule:
    """A construct whose presence disqualifies the whole expression."""

    rule_id: str
    version: int
    marker: str
    reason: str


@dataclass(frozen=True)
class RulePack:
    functions: tuple[FunctionRule, ...]
    refusals: tuple[RefusalRule, ...]


def _read(path: Path) -> dict:
    if not path.is_file():
        raise RulePackError(
            f"rule pack file is missing: {path}. Refusing to translate with a "
            "partial rule set - an absent pack and an empty one are different "
            "facts, and only one of them is a workbook nothing converts in."
        )
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RulePackError(f"{path} is not readable YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise RulePackError(f"{path} does not contain a mapping at its root")
    return loaded


def _required(entry: dict, field: str, path: Path, rule_id: str) -> object:
    value = entry.get(field)
    if value is None or value == "":
        raise RulePackError(
            f"{path}: rule {rule_id or '<unnamed>'} has no '{field}'. A rule "
            "that names only half a mapping would narrow the supported set "
            "without saying so."
        )
    return value


def load_pack(directory: Path) -> RulePack:
    """Read and validate a pack. Raises rather than returning a partial one."""
    functions: list[FunctionRule] = []
    for entry in _read(directory / "functions.yaml").get("functions") or ():
        rule_id = str(entry.get("rule_id") or "")
        functions.append(
            FunctionRule(
                rule_id=str(_required(entry, "rule_id", directory, rule_id)),
                version=int(_required(entry, "version", directory, rule_id)),
                source_function=str(_required(entry, "source", directory, rule_id)),
                target_function=str(_required(entry, "target", directory, rule_id)),
                strategy=str(entry.get("strategy", "deterministic")),
                confidence=float(entry.get("confidence", 1.0)),
                note=str(entry.get("note", "")),
            )
        )

    refusals: list[RefusalRule] = []
    for entry in _read(directory / "refusals.yaml").get("refusals") or ():
        rule_id = str(entry.get("rule_id") or "")
        refusals.append(
            RefusalRule(
                rule_id=str(_required(entry, "rule_id", directory, rule_id)),
                version=int(_required(entry, "version", directory, rule_id)),
                marker=str(_required(entry, "marker", directory, rule_id)),
                reason=" ".join(
                    str(_required(entry, "reason", directory, rule_id)).split()
                ),
            )
        )

    _check_ids(functions, refusals, directory)
    # Sorted by id, not by position in the file: the order rules fire in is
    # content, and a reordered file must not change what the engine does.
    return RulePack(
        functions=tuple(sorted(functions, key=lambda rule: rule.rule_id)),
        refusals=tuple(sorted(refusals, key=lambda rule: rule.rule_id)),
    )


def _check_ids(
    functions: list[FunctionRule], refusals: list[RefusalRule], directory: Path
) -> None:
    seen: set[str] = set()
    for rule in (*functions, *refusals):
        if rule.rule_id in seen:
            raise RulePackError(
                f"{directory}: rule id {rule.rule_id!r} appears twice. One "
                "would shadow the other, and shadowing is silent."
            )
        seen.add(rule.rule_id)


@lru_cache(maxsize=1)
def _pack() -> RulePack:
    return load_pack(PACK_DIR)


def function_rules() -> tuple[FunctionRule, ...]:
    return _pack().functions


def refusal_rules() -> tuple[RefusalRule, ...]:
    return _pack().refusals


def rule_for_function(name: str) -> FunctionRule | None:
    """The rule that maps `name`, so a translation can cite what produced it."""
    for rule in function_rules():
        if rule.source_function == name:
            return rule
    return None
