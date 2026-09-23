---
name: run-t2pbi
description: Build, run, drive, screenshot, and test t2pbi - the Tableau-to-Power-BI converter and its pywebview desktop app. Use when asked to run or start the app, launch the desktop window, take a screenshot of the UI, convert a workbook, smoke-test the engine, or verify a change end to end.
---

# Running t2pbi

t2pbi converts Tableau `.twb`/`.twbx` workbooks into Power BI PBIP projects. It is
a Python engine plus a **pywebview desktop shell** that hosts a built React UI in
the WebView2 runtime that ships with Windows. There is no Qt.

Drive it with **`.claude/skills/run-t2pbi/driver.py`**, which covers the three
layers changes actually land on. All paths below are relative to the repo root.

| layer | command | needs a window? |
|---|---|---|
| engine | `driver.py smoke` | no |
| desktop bridge | `driver.py api` | no |
| real UI | `driver.py window --shot out.png` | yes |

## Prerequisites (Windows)

Verified on Windows 11, Python 3.14.4, Node 24.14.1.

```bash
pip install pywebview lxml
```

WebView2 is preinstalled on Windows 11. Confirm it:

```bash
ls -d "/c/Program Files (x86)/Microsoft/EdgeWebView/Application"
```

## Build the interface

The built assets land in `engines/t2pbi/desktop/web/`, which is **gitignored** — a
fresh clone has none, and the shell refuses to start without them.

```bash
cd ui && npm install && npm run build
```

## Run (agent path)

Engine only. Converts, then asserts every emitted table carries a partition:

```bash
python .claude/skills/run-t2pbi/driver.py smoke
```

```
converted Superstore.twb in 83 ms -> C:\Users\...\t2pbi-38pefrn7
  events 128  crossed 82  held 46
  11 table files, 22 page entries
OK
```

The exact bridge object the window calls, without opening one. Use this for
changes to `desktop/shell.py` or `assist.py`:

```bash
python .claude/skills/run-t2pbi/driver.py api
```

The real window: launches it, runs a conversion through the page, reads the
rendered DOM back, and writes a PNG.

```bash
python .claude/skills/run-t2pbi/driver.py window --shot /tmp/win.png
```

```
page shows 8 landed rows, 40 held rows
saved /tmp/win.png (1280 x 860)
OK
```

Add `--keep-open` to leave the window up, `--settle 12` to let the stream finish
on a large workbook, `--workbook path.twb` for a different file.

**Look at the PNG.** A blank dark rectangle means WebView2 loaded but the bundle
did not — rebuild `ui/`.

## Iterating on the UI without the window

The UI runs standalone in a browser against a fixture recorded from a real
conversion, which is much faster than relaunching the window:

```bash
cd ui && npx vite --port 5199 --strictPort
node shot.mjs /tmp/ui.png 6500 ".helditem::Sales Forecast" ".btn--draft"
```

`ui/shot.mjs` drives the page with the Chrome already installed on the machine
(no bundled browser). Args: output path, ms to wait, a `selector::text` to click,
and an optional second selector.

## Run (human path)

```bash
python -m engines.t2pbi.desktop.shell
```

Opens a window titled `t2pbi`. Close it to exit. Not scriptable — see Gotchas.

Headless conversion:

```bash
python -m engines.t2pbi.cli convert testing_content/Superstore.twb --out ./out
```

## Test

```bash
python -m pytest -q
```

115 tests, about 20 seconds. `tests/conftest.py` puts `src/` on the path, so
pytest needs no `PYTHONPATH`.

## Gotchas

- **`testing_content/` is gitignored.** A fresh clone has no sample workbook. The
  driver says so and exits rather than failing obscurely. Pass `--workbook`.
- **Screen-grabbing the window returns the wrong picture.** `SetForegroundWindow`
  is refused for background processes on Windows, so `CopyFromScreen` captures
  whatever is physically on screen at those coordinates — someone else's browser
  tab, not the app. `shot_window.ps1` uses `PrintWindow` with
  `PW_RENDERFULLCONTENT` (flag `2`), which reads the window's own pixels
  regardless of z-order. This is why the capture is a separate script.
- **The Open button raises a native file dialog that blocks the webview thread**
  and cannot be dismissed programmatically. The driver stubs
  `window.pywebview.api.pick_workbook` from JS before clicking, which is the only
  way to drive a conversion in the real window.
- **`webview.__version__` does not exist.** `import webview` succeeding is the
  check; `pip show pywebview` gives the version.
- **The `t2pbi` console script is not on PATH** unless you `pip install -e .`.
  Every command here uses `python -m ...` instead.
- **Bash heredocs in this environment eat backslashes and em-dashes.** Writing
  Python or JS containing `\n`, `\\`, or `—` through `<<'PY'` silently corrupts
  it — this produced a `SyntaxError: Non-UTF-8 code` and an unterminated string
  literal. Use the Write tool, or forward slashes in Windows paths.
- **Bash working directory persists between calls but shell state does not.** A
  second `cd ui` fails, and everything `&&`-chained after it is skipped silently.
- **Local AI assist needs Ollama on `127.0.0.1:11434`.** With nothing listening,
  `suggest_dax` returns `None` and the panel says assist is off. That is the
  designed behaviour, not a failure — there is no cloud fallback by design.
- **The dev fixture and the assist stub never ship.** Both are behind
  `import.meta.env.DEV`. Confirm after a build:
  `grep -l "CommissionProjection\|llama3.1" engines/t2pbi/desktop/web/assets/*.js`
  should match nothing.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `The interface has not been built yet (looked in ...\web)` | `cd ui && npm run build` |
| `ModuleNotFoundError: No module named 'engines'` | Prefix with nothing — the repo root is enough |
| `driver.py window` prints `FAIL: the page never rendered converted rows` | The bundle is stale or missing; rebuild `ui/`, then re-run with `--keep-open` and look at the window |
| Screenshot shows unrelated content | You used a screen grab, not `PrintWindow`. Use `shot_window.ps1` |
| `Failed to launch the browser process: Code: 0` from `ui/shot.mjs` | Chrome needs its own profile: the script passes `--user-data-dir`; check that `$TEMP` is writable |
| Window opens but stays empty | WebView2 loaded a missing bundle. `ls engines/t2pbi/desktop/web/assets/` |
