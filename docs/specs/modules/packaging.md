# Module Spec — Packaging (Windows .exe)

**Code:** `packaging/t2pbi.spec`, `packaging/entry_app.py`

## Purpose
Ship the desktop app as a self-contained Windows executable so customers do not need
Python or pip. This is what we hand to a pilot customer.

## Inputs
- The installed project (`t2pbi/`) + `PySide6` + `lxml` in the build environment.

## Outputs
- `dist/t2pbi/t2pbi.exe` (one-folder build) — launches the desktop app.

## Design
- **`packaging/entry_app.py`** — tiny entry point that calls
  `t2pbi.desktop.app.main()`. PyInstaller analyses from here.
- **`packaging/t2pbi.spec`** — PyInstaller spec:
  - one-folder build (faster startup, easier to antivirus-whitelist than one-file);
  - `name="t2pbi"`, `console=False` (GUI app, no console window);
  - add `src` to `pathex` so `t2pbi` imports resolve;
  - rely on PyInstaller's PySide6 hook for Qt plugins/DLLs.

## Build
```bash
pip install -e ".[dev]"      # includes pyinstaller + PySide6
pyinstaller packaging/t2pbi.spec --noconfirm
# -> dist/t2pbi/t2pbi.exe
```

## Edge cases / notes
| Case | Handling |
|---|---|
| Qt plugins missing at runtime | PySide6 hook bundles them; spec collects all submodules |
| Antivirus flags one-file exe | use one-folder build (default here) |
| Build on non-Windows | produces a non-Windows binary; we certify Windows only |

## Acceptance
- `pyinstaller packaging/t2pbi.spec` completes without errors.
- `dist/t2pbi/t2pbi.exe` exists and launches the window on Windows.
- Build artifacts (`build/`, `dist/`) are git-ignored.
