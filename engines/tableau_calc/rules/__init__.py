"""Load the DAX -> Tableau rule pack (`P6b.2`).

The mirror of `t2pbi/core/dax/rules`, and it keeps that module's one
non-negotiable property: **a malformed pack raises rather than loading the part
of it that parsed.** A Python dict cannot lose an entry between two runs; a file
can — a bad merge, a truncated write, a duplicate id shadowing its twin — and
none of those raise on their own. A lost rule converts one formula fewer,
reports it as needing a person, and is indistinguishable from a model that never
converted it.

## What this pack carries that the forward one does not

**Argument counts.** Going the other way, a name is not enough. `IF(a, b)` is
legal DAX and there is no two-argument `IIF`. `LEFT(text)` is legal DAX, where
the length defaults to 1, and there is no one-argument Tableau `LEFT`. A rule
that mapped only the name would emit a call Tableau rejects — or worse, one it
accepts with a different meaning — so every rule states the arity it is valid
for and the translator refuses anything outside it.

The loader is deliberately separate from the forward one rather than shared. The
two packs disagree about what a rule *is*, and a shared loader would have to
carry both shapes and check neither properly.
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
    """A DAX function that becomes a Tableau function by renaming it.

    `min_args`/`max_args` are the arities at which the rename is *correct*, not
    the arities DAX allows. Where they are narrower, the difference is the
    point: `LEFT` allows one argument in DAX and requires two in Tableau.
    """

    rule_id: str
    version: int
    source_function: str
    target_function: str
    min_args: int
    max_args: int
    note: str = ""

    def accepts(self, count: int) -> bool:
        return self.min_args <= count <= self.max_args


@dataclass(frozen=True)
class RefusalRule:
    """A DAX construct whose presence disqualifies the whole expression."""

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
            "facts, and only one of them is a model nothing converts in."
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
    functions_file = directory / "functions.yaml"
    for entry in _read(functions_file).get("functions") or ():
        rule_id = str(entry.get("rule_id") or "")
        minimum = int(_required(entry, "min_args", functions_file, rule_id) or 0)
        maximum = int(entry["max_args"]) if entry.get("max_args") is not None else minimum
        if maximum < minimum:
            raise RulePackError(
                f"{functions_file}: rule {rule_id} accepts no argument count at "
                f"all ({minimum}..{maximum}), so it could never fire."
            )
        functions.append(
            FunctionRule(
                rule_id=str(_required(entry, "rule_id", functions_file, rule_id)),
                version=int(_required(entry, "version", functions_file, rule_id)),
                source_function=str(
                    _required(entry, "source", functions_file, rule_id)
                ).upper(),
                target_function=str(_required(entry, "target", functions_file, rule_id)),
                min_args=minimum,
                max_args=maximum,
                note=str(entry.get("note", "")),
            )
        )

    refusals: list[RefusalRule] = []
    refusals_file = directory / "refusals.yaml"
    for entry in _read(refusals_file).get("refusals") or ():
        rule_id = str(entry.get("rule_id") or "")
        refusals.append(
            RefusalRule(
                rule_id=str(_required(entry, "rule_id", refusals_file, rule_id)),
                version=int(_required(entry, "version", refusals_file, rule_id)),
                marker=str(_required(entry, "marker", refusals_file, rule_id)).upper(),
                reason=" ".join(
                    str(_required(entry, "reason", refusals_file, rule_id)).split()
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
    wanted = name.upper()
    for rule in function_rules():
        if rule.source_function == wanted:
            return rule
    return None
