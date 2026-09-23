# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the t2pbi desktop app (one-folder Windows build).

Build:  pyinstaller packaging/t2pbi.spec --noconfirm
Output: dist/t2pbi/t2pbi.exe
See docs/specs/modules/packaging.md.
"""

import os

# SPECPATH is the directory containing this spec (…/packaging); root is its parent.
ROOT = os.path.dirname(SPECPATH)
ENGINES = os.path.join(ROOT, "engines")
ENTRY = os.path.join(SPECPATH, "entry_app.py")

# The DAX rule pack is YAML read at runtime, not imported, so PyInstaller does
# not find it by following imports. Left out, the frozen app raises
# RulePackError on the first conversion.
RULES = os.path.join(ENGINES, "t2pbi", "core", "dax", "rules")

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=[],
    datas=[(os.path.join(RULES, "*.yaml"), "engines/t2pbi/core/dax/rules")],
    hiddenimports=["engines.t2pbi"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="t2pbi",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app: no console window
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="t2pbi",
)
