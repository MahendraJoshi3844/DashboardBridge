#!/usr/bin/env python
"""Launch and drive t2pbi from a script. Agent tooling, not product code.

Three layers, because PRs land on different ones:

  smoke   the conversion engine end to end, no UI at all
  api     the exact bridge object the desktop window calls
  window  the real WebView2 window: launch, convert, screenshot, quit

Run from the repo root:

    python .claude/skills/run-t2pbi/driver.py smoke
    python .claude/skills/run-t2pbi/driver.py api
    python .claude/skills/run-t2pbi/driver.py window --shot out.png
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# The repo root, so no PYTHONPATH is needed to run this. Since `P2.1` there is
# one import root instead of two - the engine lives at `engines/t2pbi` - and a
# driver that has to be invoked a particular way is a driver that gets invoked
# the wrong way.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

REPO = Path(__file__).resolve().parents[3]
DEFAULT_WORKBOOK = REPO / "testing_content" / "Superstore.twb"
SHOT_PS1 = Path(__file__).resolve().parent / "shot_window.ps1"
WINDOW_TITLE = "t2pbi"


def _workbook(arg: str | None) -> Path:
    path = Path(arg) if arg else DEFAULT_WORKBOOK
    if not path.is_file():
        sys.exit(
            f"No workbook at {path}.\n"
            "Pass --workbook, or put a .twb in testing_content/ "
            "(that folder is gitignored, so a fresh clone has none)."
        )
    return path


def _report(timeline) -> None:
    crossed, held = timeline.crossed(), timeline.held()
    print(f"  events {len(timeline.events)}  crossed {len(crossed)}  held {len(held)}")
    for event in held[:3]:
        print(f"    held: {event.kind} {event.name} - {event.detail[:64]}")


# --------------------------------------------------------------------------
# smoke: the engine, no UI
# --------------------------------------------------------------------------


def cmd_smoke(args: argparse.Namespace) -> int:
    from engines.t2pbi.events import EventSink
    from engines.t2pbi.pipeline import run

    source = _workbook(args.workbook)
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="t2pbi-"))
    sink = EventSink()

    started = time.perf_counter()
    result = run(source, out, source.stem, sink=sink)
    elapsed = (time.perf_counter() - started) * 1000

    print(f"converted {source.name} in {elapsed:.0f} ms -> {out}")
    print(f"  {result.stats}")
    _report(result.timeline)

    tables = sorted((out / f"{source.stem}.SemanticModel" / "definition" / "tables").glob("*.tmdl"))
    pages = sorted((out / f"{source.stem}.Report" / "definition" / "pages").iterdir())
    print(f"  {len(tables)} table files, {len(pages)} page entries")

    missing = [t.name for t in tables if "partition" not in t.read_text(encoding="utf-8")]
    if missing:
        print(f"FAIL: tables with no partition: {missing}")
        return 1
    if not result.pbip_path.exists():
        print("FAIL: no .pbip written")
        return 1
    print("OK")
    return 0


# --------------------------------------------------------------------------
# api: the bridge the window calls
# --------------------------------------------------------------------------


def cmd_api(args: argparse.Namespace) -> int:
    from engines.t2pbi.assist import runtime_available
    from engines.t2pbi.desktop.shell import Api, web_root

    source = _workbook(args.workbook)
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="t2pbi-api-"))

    index = web_root() / "index.html"
    print(f"web assets: {index} {'OK' if index.is_file() else 'MISSING - run npm run build in ui/'}")

    api = Api()
    payload = api.convert(str(source), str(out))
    print(f"convert() keys: {sorted(payload)}")
    print(f"  stats: {payload['stats']}")
    print(f"  events: {len(payload['timeline']['events'])}")
    json.dumps(payload)  # the bridge serialises to JS; fail loudly if it cannot

    print(f"assist runtime on loopback: {runtime_available()}")
    held = [e for e in payload["timeline"]["events"] if e["outcome"] == "held" and e["kind"] == "calc"]
    if held:
        ref = held[0]["ref"]
        print(f"suggest_dax({ref!r}) -> {api.suggest_dax(ref)}")

    if not index.is_file():
        return 1
    print("OK")
    return 0


# --------------------------------------------------------------------------
# window: the real WebView2 window
# --------------------------------------------------------------------------


def _screenshot(path: Path) -> bool:
    """Capture the window's own pixels. See shot_window.ps1 for why not a screengrab."""
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(SHOT_PS1), "-Title", WINDOW_TITLE, "-Out", str(path)],
        capture_output=True, text=True,
    )
    print((proc.stdout or proc.stderr).strip())
    return proc.returncode == 0


def cmd_window(args: argparse.Namespace) -> int:
    import webview

    from engines.t2pbi.desktop.shell import Api, create_app_window, web_root

    source = _workbook(args.workbook)
    index = web_root() / "index.html"
    if not index.is_file():
        sys.exit(f"No built interface at {index}. Run: cd ui && npm install && npm run build")

    shot = Path(args.shot).resolve() if args.shot else None
    window = create_app_window(Api())
    state = {"ok": False}

    def drive() -> None:
        try:
            time.sleep(3)  # WebView2 boot + first paint
            # The real Open button raises a native file dialog, which blocks the
            # webview thread and cannot be dismissed from here. Stubbing the
            # picker in the page is the only way to drive a conversion.
            window.evaluate_js(
                "window.pywebview.api.pick_workbook = "
                f"() => Promise.resolve({json.dumps(str(source))});"
                "document.querySelector('.open').click(); true"
            )
            time.sleep(args.settle)
            crossed = window.evaluate_js(
                "document.querySelectorAll('.landed__row').length"
            )
            held = window.evaluate_js("document.querySelectorAll('.helditem').length")
            print(f"page shows {crossed} landed rows, {held} held rows")
            if shot:
                _screenshot(shot)
            state["ok"] = bool(held)
        except Exception as exc:  # surfaced, never swallowed
            print(f"drive failed: {exc}")
        finally:
            if not args.keep_open:
                window.destroy()

    threading.Thread(target=drive, daemon=True).start()
    webview.start()
    print("OK" if state["ok"] else "FAIL: the page never rendered converted rows")
    return 0 if state["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Drive t2pbi.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name, fn, helptext in (
        ("smoke", cmd_smoke, "convert a workbook through the engine"),
        ("api", cmd_api, "exercise the desktop bridge without a window"),
        ("window", cmd_window, "launch the real window, convert, screenshot"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--workbook", default=None)
        p.set_defaults(fn=fn)
        if name in {"smoke", "api"}:
            p.add_argument("--out", default=None)
        if name == "window":
            p.add_argument("--shot", default=None, help="write a PNG of the window")
            p.add_argument("--settle", type=float, default=8.0,
                           help="seconds to let the stream play before capture")
            p.add_argument("--keep-open", action="store_true")

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
