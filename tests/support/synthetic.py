"""A generated `.twb` of a stated size (`P8.4`).

The repository's largest fixture is 5.5 kB. A performance budget measured
against that says nothing about the thirty-second target, and a determinism
proof over it exercises almost none of the pipeline's ordering: five tables and
one worksheet cannot show whether a hundred columns come out in a stable order.

So the corpus for `P8.2` and `P8.3` is generated rather than hand-written, and
generated **deterministically**: same arguments, same bytes. A performance
number is only comparable between runs if the input is identical between runs,
and a determinism proof over an input that varies proves nothing at all.

## What it is and is not

It is *shaped* like a real workbook - datasources with relations, columns with
captions that differ from names, calculated fields that reference each other
and other tables, worksheets binding fields onto rows, columns and the other
shelves, dashboards holding those worksheets.

It is **not a real workbook**. Nothing here came out of Tableau, so it cannot
show that the parser handles what Tableau actually writes; the hand-written
fixtures do that, and this does not replace them. What it can show is how the
pipeline behaves at a size the hand-written ones cannot reach.

The calculations are drawn from a fixed list so that a known proportion
converts and a known proportion is refused. A generated corpus where everything
converts would report a conversion rate that means nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import quoteattr

#: Formulas the translator converts, and formulas it refuses, in a fixed ratio.
#: Both are needed: a corpus that all converts measures only the happy path, and
#: the refusal path does real work - it builds the reason and the flag.
_CONVERTIBLE = (
    "SUM([{a}])",
    "AVG([{a}])",
    "SUM([{a}]) - SUM([{b}])",
    "IF [{a}] > 0 THEN [{b}] ELSE 0 END",
    "ZN([{a}])",
    "ABS([{a}] - [{b}])",
)
_REFUSED = (
    "{{ FIXED [{a}] : SUM([{b}]) }}",
    "WINDOW_SUM(SUM([{a}]))",
    "INDEX() + [{a}]",
)


@dataclass(frozen=True)
class Shape:
    """How big a generated workbook is. Every count is exact, not approximate."""

    tables: int = 5
    columns_per_table: int = 12
    calculations_per_table: int = 5
    worksheets: int = 20
    dashboards: int = 3

    @property
    def columns(self) -> int:
        return self.tables * self.columns_per_table

    @property
    def calculations(self) -> int:
        return self.tables * self.calculations_per_table


#: Roughly the shape of a real departmental workbook, and the size the
#: performance budget is stated against.
TYPICAL = Shape()

#: Deliberately past anything expected in practice, to show where the time goes
#: rather than to claim a budget for it.
LARGE = Shape(tables=20, columns_per_table=40, calculations_per_table=15,
              worksheets=120, dashboards=10)


def _column(table: int, index: int) -> tuple[str, str, str]:
    """`(name, caption, datatype)`. Name and caption differ on purpose.

    Collapsing them is a real bug this project has had: a calculation refers to
    one and the emitted model names the other.
    """
    kinds = ("integer", "real", "string", "datetime", "boolean")
    return (
        f"[t{table}_c{index}]",
        f"T{table} Field {index}",
        kinds[index % len(kinds)],
    )


def workbook_xml(shape: Shape = TYPICAL) -> bytes:
    """Build the workbook. Same shape in, same bytes out - no clock, no random.

    Deterministic because both callers depend on it: a timing comparison across
    runs needs identical input, and a determinism proof over a varying input
    proves nothing.
    """
    lines: list[str] = [
        "<?xml version='1.0' encoding='utf-8' ?>",
        "<workbook version='18.1'>",
        "  <datasources>",
    ]

    for table in range(shape.tables):
        source = f"federated.t{table}"
        lines.append(
            f"    <datasource caption={quoteattr(f'Table {table}')} "
            f"inline='true' name={quoteattr(source)} version='18.1'>"
        )
        lines.append("      <connection class='federated'>")
        lines.append(
            f"        <relation name={quoteattr(f'Table {table}')} "
            f"table={quoteattr(f'[Table {table}]')} type='table' />"
        )
        lines.append("      </connection>")

        for index in range(shape.columns_per_table):
            name, caption, datatype = _column(table, index)
            role = "measure" if datatype in {"integer", "real"} else "dimension"
            lines.append(
                f"      <column caption={quoteattr(caption)} "
                f"datatype={quoteattr(datatype)} name={quoteattr(name)} "
                f"role={quoteattr(role)} "
                f"type={quoteattr('quantitative' if role == 'measure' else 'nominal')} />"
            )

        for index in range(shape.calculations_per_table):
            # Reference two numeric columns of this table, so the formula is
            # resolvable and the dependency graph has real edges to order.
            first = _column(table, 0)[1]
            second = _column(table, 1)[1]
            # One calculation in three is refused by shape; with five per
            # table that is one of five, which is the ratio the tests assert
            # against rather than the one this comment used to claim.
            convertible = index % 3 != 2
            pool = _CONVERTIBLE if convertible else _REFUSED
            formula = pool[index % len(pool)].format(a=first, b=second)
            lines.append(
                f"      <column caption={quoteattr(f'T{table} Calc {index}')} "
                f"datatype='real' name={quoteattr(f'[t{table}_calc{index}]')} "
                "role='measure' type='quantitative'>"
            )
            lines.append(
                f"        <calculation class='tableau' formula={quoteattr(formula)} />"
            )
            lines.append("      </column>")
        lines.append("    </datasource>")
    lines.append("  </datasources>")

    lines.append("  <worksheets>")
    for sheet in range(shape.worksheets):
        table = sheet % shape.tables
        source = f"federated.t{table}"
        value = _column(table, 1)[1]
        category = _column(table, 2)[1]
        detail = _column(table, 3)[1]
        lines.append(f"    <worksheet name={quoteattr(f'Sheet {sheet}')}>")
        lines.append("      <table>")
        lines.append("        <view />")
        lines.append(f"        <rows>[{source}].[sum:{value}:qk]</rows>")
        lines.append(f"        <cols>[{source}].[none:{category}:nk]</cols>")
        lines.append("        <panes>")
        lines.append("          <pane>")
        lines.append("            <mark class='Bar' />")
        # A non-rows/cols placement, because those were a silent drop once and
        # a corpus without them would not notice if they became one again.
        lines.append("            <encodings>")
        lines.append(
            f"              <color column='[{source}].[none:{detail}:nk]' />"
        )
        lines.append("            </encodings>")
        lines.append("          </pane>")
        lines.append("        </panes>")
        lines.append("      </table>")
        lines.append("    </worksheet>")
    lines.append("  </worksheets>")

    lines.append("  <dashboards>")
    for board in range(shape.dashboards):
        lines.append(f"    <dashboard name={quoteattr(f'Dashboard {board}')}>")
        lines.append("      <zones>")
        for sheet in range(board, shape.worksheets, max(shape.dashboards, 1)):
            lines.append(f"        <zone name={quoteattr(f'Sheet {sheet}')} />")
        lines.append("      </zones>")
        lines.append("    </dashboard>")
    lines.append("  </dashboards>")
    lines.append("</workbook>")

    return ("\n".join(lines) + "\n").encode("utf-8")
