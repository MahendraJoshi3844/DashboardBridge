"""What each calculation depends on, resolved the way Tableau scopes a name.

`P3.2`, 06-conversion-engine.md, "Orchestrator". The grain fixpoint already
existed; this is the graph it and the translator were missing.

## Why a graph at all

A field reference in a Tableau formula is written `[Sales]` and means "the
`Sales` in scope here" - and what is in scope depends on the calculation's own
table. Resolving that name against every table at once produces two failures
that look nothing alike and are the same mistake:

* `Orders.Profit Ratio` = `sum([Profit])/sum([Sales])` reads `Orders`'s own
  `Sales` column. If some other table holds a *calculation* named `Sales` that
  was refused, a propagation rule that asks "does `[Sales]` appear in the DAX?"
  finds it inside `'Orders'[Sales]` and refuses a working translation.
* The same clash reaches grain classification, which sees the name in its map
  of calculation kinds and reports "cannot aggregate 'Sales': it converts to a
  measure" about a column that is not that calculation at all.

Neither emits wrong DAX - the engine refuses instead of guessing, which is the
right bias - but both hold an item that never needed holding, and say so in a
document a client reads.

## Resolution order

Deliberately the same order `_build_context` and `_resolve_references` use, so
the graph and the translator cannot disagree about what a name means:

1. a parameter alias - parameters take precedence over any same-named column;
2. a column of the calculation's **own** table;
3. a column of any table, in workbook order;
4. nothing - an unresolved name, which is not a dependency.

An edge exists only when the resolved target is itself a calculation. A
reference to a physical column is not a dependency: the column is already there.

No grain is needed to build this, which is what breaks the circularity - grain
classification needs the resolution, and the resolution needs only the IR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from t2pbi.core.dax.refs import REF_RE
from t2pbi.ir import Column, Workbook


@dataclass(frozen=True)
class Resolved:
    """Where a name in a formula actually points."""

    table: str
    name: str
    is_calculated: bool

    @property
    def key(self) -> str:
        """`"Table.Display Name"` - the same address flags and events use."""
        return f"{self.table}.{self.name}"


class Scope:
    """Name resolution for one workbook, table by table."""

    def __init__(self, wb: Workbook) -> None:
        self._params = {
            alias
            for param in wb.parameters
            for alias in (param.name.lower(), param.caption.lower())
            if alias
        }
        # Per table, then the workbook-wide fallback. `setdefault` keeps the
        # first table that declares a name, which is what makes the fallback
        # stable across runs rather than dependent on dict iteration order.
        self._local: dict[str, dict[str, Column]] = {}
        self._global: dict[str, tuple[str, Column]] = {}
        for table in wb.all_tables():
            local = self._local.setdefault(table.name, {})
            for col in table.columns:
                for alias in (col.name.lower(), col.display_name.lower()):
                    if not alias:
                        continue
                    local.setdefault(alias, col)
                    self._global.setdefault(alias, (table.name, col))

    def resolve(self, name: str, from_table: str) -> Resolved | None:
        alias = name.lower()
        if alias in self._params:
            return None
        local = self._local.get(from_table, {})
        if alias in local:
            col = local[alias]
            return Resolved(from_table, col.display_name, col.is_calculated)
        found = self._global.get(alias)
        if found is None:
            return None
        table, col = found
        return Resolved(table, col.display_name, col.is_calculated)

    def references(self, formula: str, from_table: str) -> list[Resolved]:
        """Every name in `formula`, resolved. Order preserved, duplicates kept
        out, so a caller can rely on it without sorting."""
        seen: dict[str, Resolved] = {}
        for match in REF_RE.finditer(formula or ""):
            target = self.resolve(match.group(1), from_table)
            if target is not None:
                seen.setdefault(target.key, target)
        return list(seen.values())


@dataclass(frozen=True)
class DependencyGraph:
    """Calculation key -> the calculation keys it reads."""

    edges: dict[str, frozenset[str]]

    def order(self) -> tuple[list[str], list[str]]:
        """Dependency order, and the keys that have none because they cycle.

        Kahn's algorithm over a *sorted* ready set: two runs of one workbook
        must translate in the same order, and "whatever the dict yielded" is
        not an order.

        A cycle cannot be converted in any order - each member needs another
        member first - so its keys come back separately rather than being
        dropped into the sequence at an arbitrary point.
        """
        remaining = {key: set(deps) for key, deps in self.edges.items()}
        ordered: list[str] = []
        while True:
            ready = sorted(key for key, deps in remaining.items() if not deps)
            if not ready:
                break
            for key in ready:
                ordered.append(key)
                del remaining[key]
            for deps in remaining.values():
                deps.difference_update(ready)
        return ordered, sorted(remaining)

    def dependents_of(self, refused: Iterable[str]) -> set[str]:
        """Everything that transitively reads any of `refused`."""
        blocked = set(refused)
        while True:
            grown = {
                key
                for key, deps in self.edges.items()
                if key not in blocked and deps & blocked
            }
            if not grown:
                return blocked - set(refused)
            blocked |= grown


def build(wb: Workbook, scope: Scope | None = None) -> tuple[DependencyGraph, Scope]:
    """The graph, and the scope it was resolved with (callers need both)."""
    scope = scope or Scope(wb)
    edges: dict[str, frozenset[str]] = {}
    for table in wb.all_tables():
        for col in table.columns:
            if not col.is_calculated:
                continue
            key = f"{table.name}.{col.display_name}"
            edges[key] = frozenset(
                target.key
                for target in scope.references(col.formula or "", table.name)
                if target.is_calculated and target.key != key
            )
    return DependencyGraph(edges=edges), scope
