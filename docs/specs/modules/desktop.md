# Module Spec — Desktop App

**Code:** `t2pbi/desktop/` (`worker.py`, `app.py`)

## Purpose
Milestone 6. A thin, offline PySide6 GUI over `pipeline.run()`. The UI never does
conversion logic itself and never blocks the main thread.

## Inputs (from the user)
- An input `.twb`/`.twbx` file (file picker).
- An output directory (folder picker).
- Optional project name (defaults to the input file stem).

## Outputs
- A PBIP project + Migration Report in the chosen folder (produced by the engine).
- On screen: progress, a one-line summary, and buttons to open the report / output
  folder.

## Design
- **`worker.py`**
  - `run_job(input_path, out_dir, name) -> JobSummary` — a **pure, Qt-free** function
    wrapping `pipeline.run()`; returns a dict-like summary (stats + paths) or raises.
    This is what tests exercise (no display needed).
  - `ConvertWorker(QObject)` — wraps `run_job` on a `QThread`; emits
    `progress(int, str)`, `finished(dict)`, `failed(str)`. PySide6 is imported lazily
    so the engine/tests don't require it.
- **`app.py`**
  - `MainWindow` — input/output pickers, Convert button, progress bar, status label,
    "Open report" / "Open folder" actions. Disables Convert while running.
  - `main()` — `python -m t2pbi.desktop.app`.

## Edge cases
| Case | Handling |
|---|---|
| Invalid workbook | show the engine's error message; re-enable Convert |
| No input / output chosen | Convert disabled until both set |
| Long conversion | runs on worker thread; UI stays responsive |
| PySide6 not installed | `app.main()` prints an install hint and exits non-zero |

## Acceptance
- `run_job` converts a sample workbook and returns correct stats/paths (headless test).
- App launches, converts, and opens the report — verified manually on Windows.
- No conversion logic lives in `app.py`; it only calls the worker.
