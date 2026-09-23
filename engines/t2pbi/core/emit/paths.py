"""Turning a name from a workbook into one path component, safely.

Every name this emitter puts in a path — the project's, a table's, a
parameter's — came out of a `.twb` file or from whoever named the project.
`sanitize_name` in `tmdl` is not the function for that job: it makes a name safe
to sit inside a *TMDL identifier*, so it removes quotes and newlines and leaves
everything else alone. A backslash is perfectly legal in a TMDL identifier and
is a directory separator on the way to disk.

The concrete failure that produced this module: a project named
`<script>alert(xss)<\\script>` made the emitter try to create
`…\\<script>alert(xss)<\\script>.SemanticModel\\definition`, which on Windows is
both an invalid name and, because of the backslash, a second directory level
nobody asked for. Replace the angle brackets with `..` and the same path walks
out of the output directory entirely.

So: one function, used for every path component, that can only ever return a
single ordinary file name.
"""

from __future__ import annotations

import re

#: Illegal in a Windows path component, plus the separators, plus control
#: characters. A superset of what POSIX forbids, deliberately: the output is a
#: Power BI project and those are opened on Windows.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: Windows refuses these as file names whatever the extension, which is a
#: surprising way for a conversion to fail on one workbook in a thousand.
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)

_FALLBACK = "Unnamed"


def safe_path_name(name: str, fallback: str = _FALLBACK) -> str:
    """Reduce a name to one safe path component. Deterministic.

    Same input, same output, always: the project's rule is that two conversions
    of one workbook produce identical trees, and a name that sanitised
    differently on two runs would break that before anything else did.

    Nothing here tries to preserve the original name faithfully. A name that
    reaches this function has already failed to be a file name, and a readable
    approximation is worth more than an exact one that cannot be written.
    """
    cleaned = _ILLEGAL.sub("", name)
    # A component of "." or ".." is the traversal itself, and Windows drops
    # trailing dots and spaces silently — which would make "a." and "a" the
    # same file while we still believed they were different.
    cleaned = cleaned.strip().rstrip(". ")
    if not cleaned:
        return fallback
    stem, _, extension = cleaned.partition(".")
    if stem.upper() in _RESERVED:
        cleaned = f"{stem}_{extension}" if extension else f"{stem}_"
    return cleaned or fallback
