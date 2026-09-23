"""Line endings are the repository's business, not each machine's.

This exists because of a corruption that cost real time to find and would have
cost more to find later. `apps/api/app/api/conversion.py` had been committed
with CRLF in the blob while `core.autocrlf` was true, so checking it out applied
the LF-to-CRLF conversion to endings that were already CRLF. Every line ending
became `\\r\\r\\n`, the file doubled in length, and it still rendered correctly in
an editor and still imported. It surfaced only because a string replacement
stopped matching.

The remedy is `.gitattributes`: with `text=auto` the blob is LF whatever the
working tree looks like, so the conversion cannot be applied twice. These tests
keep it there, because its absence is invisible until the day it is not.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_repository_declares_how_text_files_are_stored():
    attributes = ROOT / ".gitattributes"
    assert attributes.is_file(), (
        ".gitattributes is gone. Without it, whether a file is stored LF or "
        "CRLF depends on each contributor's core.autocrlf, and a CRLF blob "
        "plus autocrlf doubles every line ending on checkout."
    )
    assert "text=auto" in attributes.read_text(encoding="utf-8")


def test_no_tracked_text_file_is_stored_with_windows_line_endings():
    """The condition that makes the doubling possible, checked directly.

    Reads the *blobs*, not the working tree: the working tree is allowed to be
    CRLF on Windows and that is not the problem. The problem is a CRLF blob.
    """
    names = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=ROOT, check=True
    ).stdout.split("\n")

    offenders: list[str] = []
    for name in filter(None, names):
        blob = subprocess.run(
            ["git", "show", f"HEAD:{name}"], capture_output=True, cwd=ROOT
        ).stdout
        if b"\x00" in blob[:8000]:
            continue  # binary; line endings are not a concept here
        if b"\r\n" in blob:
            offenders.append(name)

    assert offenders == [], (
        f"{offenders} are stored with CRLF. On a machine with core.autocrlf "
        "set, checking one out doubles every line ending and the damage is "
        "invisible in an editor."
    )
