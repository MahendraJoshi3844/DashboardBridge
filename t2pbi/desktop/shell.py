"""Desktop shell: a WebView2 window over the built UI, and the bridge to the engine.

Qt is gone. This hosts static assets from disk in the WebView runtime that already
ships with Windows, so the whole shell costs about a megabyte instead of Qt's 665.

Nothing here opens a port or touches the network: the page is loaded from a local
file and every call is an in-process Python call. The offline guarantee in
CLAUDE.md holds by construction, not by policy.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from t2pbi.events import EventSink
from t2pbi.pipeline import run

WINDOW_TITLE = "t2pbi"
MIN_SIZE = (900, 620)


def web_root() -> Path:
    """Where the built UI lives, both in development and inside a PyInstaller exe."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "t2pbi" / "desktop" / "web"
    return Path(__file__).resolve().parent / "web"


class Api:
    """Everything the page may ask the engine to do.

    Each method is called from the WebView thread, so it must not block the UI
    for long or touch window state directly.
    """

    def __init__(self) -> None:
        self._window = None
        self._last_out_dir = str(Path.home() / "t2pbi-output")
        self._last_result = None  # kept so assist can look a held item back up
        self._maximized = False

    def bind(self, window) -> None:
        self._window = window

    # ---- file selection -------------------------------------------------

    def pick_workbook(self) -> str | None:
        import webview  # noqa: PLC0415

        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Tableau workbook (*.twb;*.twbx)", "All files (*.*)"),
        )
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else result

    def pick_output(self) -> str | None:
        import webview  # noqa: PLC0415

        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return None
        chosen = result[0] if isinstance(result, (list, tuple)) else result
        self._last_out_dir = chosen
        return chosen

    # ---- conversion -----------------------------------------------------

    def convert(self, input_path: str, out_dir: str = "") -> dict:
        """Run the pipeline and hand back the recording the Stage renders."""
        source = Path(input_path)
        target = Path(out_dir) if out_dir else Path(self._last_out_dir) / source.stem
        sink = EventSink()
        result = run(source, target, source.stem, sink=sink)
        self._last_result = result
        return {
            "timeline": result.timeline.to_dict(),
            "stats": result.stats,
            "pbipPath": str(result.pbip_path),
            "reportPath": str(result.report_path),
        }

    # ---- window chrome --------------------------------------------------
    # The window is frameless, so the page draws its own title bar and needs
    # these to do what the native buttons used to.

    def window_minimize(self) -> None:
        self._window.minimize()

    def window_maximize(self) -> None:
        """Toggle, so one button serves both directions."""
        if self._maximized:
            self._window.restore()
        else:
            self._window.maximize()
        self._maximized = not self._maximized

    def window_close(self) -> None:
        self._window.destroy()

    # ---- shell services -------------------------------------------------

    def open_path(self, path: str) -> bool:
        """Open a file or folder in the OS handler. Reports whether it launched,
        so the page can tell the user rather than appearing to do nothing."""
        target = Path(path)
        try:
            if sys.platform == "win32":
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError:
            return False
        return True

    # ---- local AI assist (absent until a local runtime is present) -------

    def assist_available(self) -> bool:
        from t2pbi.assist import runtime_available  # noqa: PLC0415

        return runtime_available()

    def suggest_dax(self, ref: str) -> dict | None:
        """Draft DAX for one held calculated field, using a local model only.

        `ref` is the IR reference the Stage carries on every event, so the page
        never has to send us a formula - we look it up from the last run.
        """
        from t2pbi.assist import suggest_for  # noqa: PLC0415

        if self._last_result is None:
            return None
        workbook = self._last_result.workbook
        for table in workbook.all_tables():
            for col in table.columns:
                if f"{table.name}.{col.display_name}" != ref or not col.is_calculated:
                    continue
                reason = next(
                    (
                        f.reason
                        for f in workbook.flags
                        if f.item == ref and f.stage == "translate"
                    ),
                    "The converter could not translate this safely.",
                )
                suggestion = suggest_for(
                    col.display_name, col.formula or "", reason, table.name
                )
                return suggestion.to_dict() if suggestion else None
        return None


def create_app_window(api: "Api"):
    """The one place the window is configured.

    The driver used to build its own window, which meant it verified a window
    the app never shipped - it still had the native title bar. Both go through
    here now.
    """
    import webview  # noqa: PLC0415

    window = webview.create_window(
        WINDOW_TITLE,
        url=(web_root() / "index.html").as_uri(),
        js_api=api,
        width=1280,
        height=860,
        min_size=MIN_SIZE,
        background_color="#0A0E14",
        # The native title bar is what made this read as a dated desktop tool.
        # The page draws its own; .pywebview-drag-region moves the window.
        frameless=True,
        easy_drag=False,
    )
    api.bind(window)
    return window


def main() -> int:
    try:
        import webview  # noqa: PLC0415
    except ImportError:
        print(
            "The desktop shell needs pywebview. Install it with:\n"
            "    pip install pywebview",
            file=sys.stderr,
        )
        return 1

    index = web_root() / "index.html"
    if not index.is_file():
        print(
            f"The interface has not been built yet (looked in {web_root()}).\n"
            "Build it with:\n"
            "    cd ui && npm install && npm run build",
            file=sys.stderr,
        )
        return 1

    window = create_app_window(Api())

    # `webview.start` blocks until the window closes; no thread outlives it.
    webview.start(debug=bool(os.environ.get("T2PBI_DEBUG")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
