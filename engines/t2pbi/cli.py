"""Headless CLI entry point: `t2pbi convert <input> --out <dir> [--name <project>]`."""

from __future__ import annotations

import argparse
import sys

from engines.t2pbi import __version__
from engines.t2pbi.core.extract import InvalidWorkbookError
from engines.t2pbi.pipeline import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="t2pbi", description="Convert a Tableau workbook (.twb/.twbx) to a Power BI project (PBIP)."
    )
    parser.add_argument("--version", action="version", version=f"t2pbi {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    conv = sub.add_parser("convert", help="Convert a workbook to a PBIP project.")
    conv.add_argument("input", help="Path to a .twb or .twbx file.")
    conv.add_argument("--out", required=True, help="Output directory for the PBIP project.")
    conv.add_argument("--name", default=None, help="Project name (default: input file stem).")

    args = parser.parse_args(argv)

    if args.command == "convert":
        try:
            result = run(args.input, args.out, args.name)
        except InvalidWorkbookError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        s = result.stats
        print(
            f"Converted: {s['tables']} tables, {s['columns']} columns, "
            f"{s['calculated_translated']}/{s['calculated_fields']} calcs -> DAX, "
            f"{s['flags']} flags ({s['manual_flags']} need manual work)."
        )
        print(f"PBIP:   {result.pbip_path}")
        print(f"Report: {result.report_path}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
