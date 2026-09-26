"""The §15 upload controls, one function each.

Every control here is independently callable and independently tested, because a
single `validate(upload)` that does eight things has eight ways to be silently
weakened and no way to prove which one is still working.

The order matters and is enforced by `app/api/artifacts.py`:

```
extension → declared size → streamed size + sha256 → archive limits → detection
   cheap, no bytes read        bounded, into staging     directory only    cheap
```

Nothing reaches the artifact store before all of them pass, and a `.twbx` is
**never extracted** — its central directory is read for names and declared
sizes, which is all a bomb check needs and all detection needs
(09-security-spec § Uploaded artifacts are untrusted input).

Two things this module deliberately does *not* do:

* **Parse the workbook.** Detection is an extension plus a magic-byte peek.
  Parsing is expensive, must be sandboxed, and belongs to the adapter
  (02-architecture: `detect` and `parse` are separate for exactly this reason).
* **Guess.** An inconclusive detection returns `None`, and the caller refuses
  the upload. A file that is probably a workbook is not a workbook.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from dashboardbridge_contracts.enums import ErrorCategory, Platform

from app.core.config import settings
from app.core.errors import ApiException

# ---------------------------------------------------------------------------
# what may be uploaded
# ---------------------------------------------------------------------------

#: The allow-list. An extension is a cheap first filter and nothing more — it is
#: attacker-controlled, which is why every accepted extension is confirmed
#: against the bytes by `detect_platform`.
ALLOWED_EXTENSIONS: dict[str, Platform] = {
    ".twb": Platform.TABLEAU,
    ".twbx": Platform.TABLEAU,
    # A PBIP is a *folder*, so it arrives zipped. `.zip` is the weakest claim
    # any extension can make - `.twbx` is a zip too - which is why the member
    # list decides, not the name.
    ".zip": Platform.POWERBI,
    # A MicroStrategy dossier package. A zip under another name, so it gets the
    # same archive limits; its layout is not published, so detection only
    # confirms it is an archive and the reader says what it recognised.
    ".mstr": Platform.MICROSTRATEGY,
}

#: A zipped MicroStrategy metadata export (`mstr2pbi`'s bundle): one JSON file
#: per object type. Any of these names in a `.zip` makes it one.
MICROSTRATEGY_BUNDLE_MEMBERS = frozenset(
    f"{name}.json"
    for name in (
        "attributes", "facts", "metrics", "tables", "reports", "dossiers",
        "documents", "filters", "prompts", "security_filters", "hierarchies",
    )
)

#: The extensions that arrive as archives and so need `inspect_zip_archive`.
ARCHIVE_EXTENSIONS = frozenset({".twbx", ".zip", ".mstr"})

#: Refused with a reason rather than a shrug. Telling a user "unsupported file
#: type" when the answer is "not yet, and here is what is" wastes their time and
#: ours.
#:
#: `.pbip` is here even though PBIP is now readable (`P6a`): the file of that
#: name is the project *manifest*, a few lines of JSON pointing at sibling
#: folders. On its own it describes nothing, so accepting it would produce an
#: empty inventory rather than an error. Zip the project folder instead, which
#: is what the message says.
NOT_YET_SUPPORTED: dict[str, str] = {
    ".pbix": "Power BI",
    ".pbit": "Power BI",
    ".twbr": "Tableau",
}

#: A `.pbip` on its own, with the remedy rather than a refusal.
MANIFEST_ONLY: dict[str, str] = {
    ".pbip": (
        "A .pbip file is just the project manifest - it points at the report "
        "and semantic model folders beside it, and carries none of their "
        "contents. Zip the whole project folder and upload that instead."
    ),
}

READ_CHUNK_BYTES = 1024 * 1024
HEAD_BYTES = 4096

#: Multipart framing — boundaries, part headers, the trailing epilogue — is not
#: file content, so the request body is legitimately a little larger than the
#: file. Generous enough for long filenames, far too small to matter.
MULTIPART_OVERHEAD_BYTES = 64 * 1024

_UNSAFE_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f<>:\"|?*]")
_FALLBACK_FILENAME = "upload"


def max_upload_bytes() -> int:
    return settings().max_upload_size_mb * 1024 * 1024


def _refuse(message: str, detail: str) -> ApiException:
    """An upload the boundary will not accept.

    `UNSUPPORTED_ARTIFACT` is spelled out at its two call sites rather than
    hidden behind a default here: "we will not take this" and "we cannot read
    this *yet*" are different answers and the user is owed the difference.
    """
    return ApiException(
        ErrorCategory.UPLOAD_ERROR, message, detail=detail, status_code=400
    )


# ---------------------------------------------------------------------------
# filename — display only, never a path
# ---------------------------------------------------------------------------


def sanitize_filename(raw: str | None) -> str:
    """A name safe to show a person, and useless as a path.

    The result is never used to build a location — `artifact_store.new_key()`
    does that — so this is defence in depth rather than the defence. It still
    strips directory components, because a display string containing
    `../../etc/passwd` is a name that will eventually be pasted somewhere it
    matters.
    """
    if not raw:
        return _FALLBACK_FILENAME
    # Both separators, whatever the client's platform: a POSIX server must not
    # treat `..\..\win.ini` as an ordinary name.
    name = raw.replace("\\", "/").split("/")[-1]
    name = _UNSAFE_NAME_CHARS.sub("", name).strip()
    if not name or name in (".", ".."):
        return _FALLBACK_FILENAME
    return name[:255]


def validated_extension(filename: str) -> str:
    """The lower-cased extension, having checked it against the allow-list."""
    suffix = Path(filename).suffix.lower()

    if suffix in ALLOWED_EXTENSIONS:
        return suffix

    allowed = " or ".join(sorted(ALLOWED_EXTENSIONS))
    if suffix in MANIFEST_ONLY:
        # Not "unsupported": the format is supported and this particular file
        # is the wrong part of it. The remedy is one sentence, so say it.
        raise ApiException(
            ErrorCategory.UNSUPPORTED_ARTIFACT,
            MANIFEST_ONLY[suffix],
            detail=f"{suffix!r} is a project manifest, not the project",
            status_code=400,
        )
    if suffix in NOT_YET_SUPPORTED:
        platform = NOT_YET_SUPPORTED[suffix]
        raise ApiException(
            ErrorCategory.UNSUPPORTED_ARTIFACT,
            f"Reading {platform} files is not supported yet — this version "
            f"migrates Tableau workbooks into Power BI. Upload a "
            f"{allowed} file instead.",
            detail=f"extension {suffix!r} is a planned but unimplemented source (ADR-005)",
            status_code=400,
        )

    raise _refuse(
        f"That file type cannot be migrated. Upload a Tableau workbook, a "
        f"zipped Power BI project or a MicroStrategy package — a {allowed} file.",
        detail=f"extension {suffix!r} is not in the allow-list {sorted(ALLOWED_EXTENSIONS)}",
    )


# ---------------------------------------------------------------------------
# size — refused on the way in, not measured on the way out
# ---------------------------------------------------------------------------


def check_declared_size(content_length: str | int | None, limit_bytes: int) -> None:
    """Refuse an oversize body before reading a byte of it.

    `Content-Length` is attacker-controlled and so proves nothing about a file
    that turns out to be small — but a *declared* size over the limit is a free
    refusal, and the streamed check below is what actually enforces the bound.
    """
    if content_length in (None, ""):
        return
    try:
        declared = int(content_length)
    except (TypeError, ValueError):
        return
    if declared > limit_bytes + MULTIPART_OVERHEAD_BYTES:
        raise _refuse(
            f"That file is larger than this deployment accepts "
            f"({settings().max_upload_size_mb} MB). Upload a smaller workbook, "
            f"or ask your administrator to raise the limit.",
            detail=f"declared content-length {declared} exceeds limit {limit_bytes}",
        )


def oversize_body(seen_bytes: int, cap_bytes: int) -> ApiException:
    """The refusal raised from the ASGI receive channel, mid-body.

    Separate from `stream_with_limits` because it fires earlier — before the
    framework has finished buffering — and the two must say the same thing to
    the person reading it.
    """
    return _refuse(
        f"That file is larger than this deployment accepts "
        f"({settings().max_upload_size_mb} MB). Upload a smaller workbook, or "
        f"ask your administrator to raise the limit.",
        detail=f"request body reached {seen_bytes} bytes, cap is {cap_bytes}",
    )


@dataclass(frozen=True)
class StreamResult:
    size_bytes: int
    sha256: str
    head: bytes


def stream_with_limits(
    chunks: Iterable[bytes],
    *,
    sink: Callable[[bytes], object],
    limit_bytes: int,
) -> StreamResult:
    """Copy `chunks` into `sink`, hashing as they pass and stopping at the cap.

    The cap is checked *per chunk*, so an oversize upload is refused after the
    chunk that crosses the line and never after the whole file is in memory or
    on disk. That distinction is the entire control: a size check performed on a
    fully buffered file has already lost the resource-exhaustion argument.
    """
    digest = hashlib.sha256()
    total = 0
    head = b""

    for chunk in chunks:
        if not chunk:
            continue
        total += len(chunk)
        if total > limit_bytes:
            raise _refuse(
                f"That file is larger than this deployment accepts "
                f"({settings().max_upload_size_mb} MB). Upload a smaller "
                f"workbook, or ask your administrator to raise the limit.",
                detail=f"stream exceeded {limit_bytes} bytes after {total} bytes",
            )
        digest.update(chunk)
        if len(head) < HEAD_BYTES:
            head += chunk[: HEAD_BYTES - len(head)]
        sink(chunk)

    if total == 0:
        raise _refuse(
            "That file is empty. Upload the workbook you want to migrate.",
            detail="zero-length upload",
        )

    return StreamResult(size_bytes=total, sha256=digest.hexdigest(), head=head)


# ---------------------------------------------------------------------------
# archives — bounded by the directory, never by extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ZipLimits:
    """Four caps, because a bomb only has to defeat the one you left out.

    * `max_entries` — a directory of a million tiny files exhausts inodes and
      parser time without ever being large.
    * `max_entry_uncompressed_bytes` — one member that expands past memory.
    * `max_total_uncompressed_bytes` — many members that do so together.
    * `max_ratio` — the classic bomb: small on the wire, enormous expanded.
      A legitimate `.twbx` is XML and images; ratios above ~50 do not occur.
    """

    max_entries: int = 5_000
    max_entry_uncompressed_bytes: int = 512 * 1024 * 1024
    max_total_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024
    max_ratio: float = 100.0


@dataclass(frozen=True)
class ZipReport:
    entry_count: int
    total_uncompressed_bytes: int
    total_compressed_bytes: int
    names: tuple[str, ...]

    @property
    def ratio(self) -> float:
        if self.total_compressed_bytes <= 0:
            return float("inf") if self.total_uncompressed_bytes else 0.0
        return self.total_uncompressed_bytes / self.total_compressed_bytes


_BOMB_MESSAGE = (
    "That archive expands to far more data than a workbook should. It was not "
    "opened. Re-save the workbook from Tableau and upload it again."
)


def inspect_zip_archive(path: Path, limits: ZipLimits | None = None) -> ZipReport:
    """Read a zip's central directory and judge it. Extract nothing.

    `zipfile` reads only the end-of-central-directory record and the entry
    headers here; `infolist()` never touches compressed data, so a bomb is
    refused by its own declaration before a single byte is inflated.
    """
    caps = limits or ZipLimits()

    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise _refuse(
            "That file is not a valid Tableau packaged workbook (.twbx). It may "
            "be damaged, or renamed from another format. Re-save it from "
            "Tableau and try again.",
            detail=f"zipfile.BadZipFile: {exc}",
        ) from exc

    if len(entries) > caps.max_entries:
        raise _refuse(
            _BOMB_MESSAGE,
            detail=f"archive declares {len(entries)} entries, cap is {caps.max_entries}",
        )

    total_uncompressed = 0
    total_compressed = 0
    names: list[str] = []

    for entry in entries:
        if entry.file_size > caps.max_entry_uncompressed_bytes:
            raise _refuse(
                _BOMB_MESSAGE,
                detail=(
                    f"entry declares {entry.file_size} uncompressed bytes, "
                    f"per-entry cap is {caps.max_entry_uncompressed_bytes}"
                ),
            )
        total_uncompressed += entry.file_size
        total_compressed += entry.compress_size
        names.append(entry.filename)

    if total_uncompressed > caps.max_total_uncompressed_bytes:
        raise _refuse(
            _BOMB_MESSAGE,
            detail=(
                f"archive declares {total_uncompressed} total uncompressed "
                f"bytes, cap is {caps.max_total_uncompressed_bytes}"
            ),
        )

    report = ZipReport(
        entry_count=len(entries),
        total_uncompressed_bytes=total_uncompressed,
        total_compressed_bytes=total_compressed,
        names=tuple(names),
    )

    if total_uncompressed and report.ratio > caps.max_ratio:
        raise _refuse(
            _BOMB_MESSAGE,
            detail=(
                f"compression ratio {report.ratio:.1f}:1 exceeds cap "
                f"{caps.max_ratio:.1f}:1"
            ),
        )

    return report


# ---------------------------------------------------------------------------
# detection — cheap, safe, and allowed to say "I don't know"
# ---------------------------------------------------------------------------

_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

#: `Platform.POWERBI.value.title()` is "Powerbi", which is nobody's product.
_DISPLAY = {
    Platform.TABLEAU: "Tableau",
    Platform.POWERBI: "Power BI",
    Platform.MICROSTRATEGY: "MicroStrategy",
}
_TABLEAU_MARKER = b"<workbook"


def detect_platform(
    extension: str,
    *,
    head: bytes,
    zip_report: ZipReport | None = None,
) -> Platform | None:
    """Which platform produced this file, or `None` if the bytes do not say.

    An extension alone is a claim by the uploader. This confirms it against the
    first few kilobytes — a `<workbook` element for `.twb`, a zip signature plus
    a `.twb` member for `.twbx` — and nothing more. Reading the workbook is the
    adapter's job and must be sandboxed; detection runs unsandboxed and so must
    stay this small.
    """
    if extension == ".twb":
        window = head.lstrip(b"\xef\xbb\xbf").lstrip()
        if _TABLEAU_MARKER in head and (
            window.startswith(b"<?xml") or window.startswith(_TABLEAU_MARKER)
        ):
            return Platform.TABLEAU
        return None

    if extension == ".zip":
        # A zipped Power BI project. Confirmed by what is inside it, because
        # `.zip` is a claim about nothing at all.
        if not head.startswith(_ZIP_SIGNATURES) or zip_report is None:
            return None
        if any(
            name.lower().endswith((".pbip", ".pbism", ".pbir"))
            for name in zip_report.names
        ):
            return Platform.POWERBI
        if any(
            name.replace("\\", "/").rsplit("/", 1)[-1].lower() in MICROSTRATEGY_BUNDLE_MEMBERS
            for name in zip_report.names
        ):
            return Platform.MICROSTRATEGY
        return None

    if extension == ".mstr":
        # Nothing more is claimed than "a non-empty archive": the package layout
        # is unpublished, and the reader - sandboxed in analysis - reports what
        # it recognised and refuses a package with nothing it knows.
        if head.startswith(_ZIP_SIGNATURES) and zip_report and zip_report.entry_count:
            return Platform.MICROSTRATEGY
        return None

    if extension == ".twbx":
        if not head.startswith(_ZIP_SIGNATURES):
            return None
        if zip_report is None:
            return None
        # A packaged workbook contains the workbook. A zip that does not is
        # some other zip wearing a `.twbx` name.
        if any(name.lower().endswith(".twb") for name in zip_report.names):
            return Platform.TABLEAU
        return None

    return None


def refuse_undetectable(filename: str, expected: Platform | None = None) -> ApiException:
    if expected is Platform.MICROSTRATEGY:
        return _refuse(
            "We could not confirm that this file is a MicroStrategy export. Upload a "
            ".mstr dossier package from MicroStrategy Workstation, or a .zip of the "
            "metadata export (attributes.json, metrics.json, dossiers.json, ...).",
            detail=f"detection inconclusive for {filename!r}; refusing rather than guessing",
        )
    return _refuse(
        "We could not confirm that this file is a Tableau workbook. Open it in "
        "Tableau, re-save it, and upload it again.",
        detail=f"detection inconclusive for {filename!r}; refusing rather than guessing",
    )


def refuse_platform_mismatch(detected: Platform, expected: Platform) -> ApiException:
    return ApiException(
        ErrorCategory.UNSUPPORTED_ARTIFACT,
        f"This project migrates from {_DISPLAY[expected]}, but that file is a "
        f"{_DISPLAY[detected]} file. Upload a {_DISPLAY[expected]} workbook, or "
        f"start a project whose source is {_DISPLAY[detected]}.",
        detail=(
            f"detected platform {detected.value!r} contradicts the project's "
            f"source_platform {expected.value!r}; refusing rather than coercing"
        ),
        status_code=400,
    )


def refuse_malware(reason: str, scanner: str) -> ApiException:
    """Refused by the scan hook (`P7.5`).

    The person-facing message is the reason as written, because both reasons
    this can carry are already written for a person: one says the file is
    malicious, the other says the deployment is misconfigured. Telling someone
    to re-save a workbook would be wrong for both.
    """
    return _refuse(
        reason,
        f"malware scan hook refused the upload; scanner={scanner!r}",
    )
