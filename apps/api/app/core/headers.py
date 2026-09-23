"""Making untrusted text safe to put in a response header.

A filename offered for download is built from the project's name, and that name
was typed by a person or taken from an uploaded file. It reaches the
`content-disposition` header as untrusted text, inside a quoted string, on a
line whose ending is significant — three separate ways for it to mean something
other than "call the download this".
"""

from __future__ import annotations

#: A quote closes the quoted string early and lets the rest of the name be read
#: as further header parameters; a backslash escapes the character after it; a
#: semicolon starts a new parameter. Control characters — a carriage return or
#: newline above all — end the header line itself.
_UNSAFE = frozenset('";' + chr(92))

_FALLBACK = "download"


def header_safe_filename(filename: str, fallback: str = _FALLBACK) -> str:
    """Reduce a filename to something that can only name a download.

    Unsafe characters are dropped rather than escaped or percent-encoded: the
    only job this value has is to suggest a name to a save dialog, and a name
    that is merely close enough is a better outcome than a header whose
    structure a caller can choose.

    `str.isprintable()` is what excludes the control characters, and it excludes
    every one of them rather than the two that are famous.
    """
    cleaned = "".join(
        char for char in filename if char.isprintable() and char not in _UNSAFE
    ).strip()
    return cleaned or fallback
