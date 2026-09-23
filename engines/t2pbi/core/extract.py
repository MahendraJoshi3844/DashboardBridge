"""Stage 1 — Extract.

Turn a .twb/.twbx path into raw .twb XML bytes + a resource map, without ever
reading full data extracts. See docs/specs/modules/extract.md.

## The cap, and why it is here rather than only at the API (`P7.3`)

The API refuses a zip bomb by reading the archive's central directory, before
anything is inflated. That is the right cheap outer layer and it is not enough,
for two reasons found by measuring rather than reading:

* **A central directory is written by whoever made the file.** Rewriting a
  200 MB member's `file_size` to say `4096` produces an archive that passes
  every declaration-based cap - 4 KB declared, ratio 0.0 - and still holds
  200 MB of deflate stream.
* **`ZipFile.read()` inflates the whole member before the check that catches
  it.** Measured: 459 MB of peak allocation from a 204 kB file, and *then* a
  `BadZipFile` for the CRC, which can only be verified at the end. The
  exception arrives after the memory is spent.

So the member is read **incrementally against a cap on bytes actually
inflated**, and refused the moment it passes one - not when the file admits it.

`extract()` is also what the CLI and the desktop shell call, and neither goes
near the API's checks. A limit that lived only at the HTTP boundary would not be
a limit on the engine.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path


#: How much `.twb` XML this will inflate out of an archive before refusing.
#: Generous - the largest real workbook seen here is a few megabytes - because
#: the cap exists to stop an archive designed to exhaust memory, not to have an
#: opinion about how big someone's workbook is allowed to be.
MAX_TWB_BYTES = 256 * 1024 * 1024

#: Read size. Small enough that the overshoot past the cap is negligible, large
#: enough not to make a legitimate workbook slow.
_CHUNK_BYTES = 1024 * 1024


class InvalidWorkbookError(Exception):
    """Raised when the input is not a readable Tableau workbook."""


@dataclass
class ExtractResult:
    twb_bytes: bytes
    source_format: str  # "twb" | "twbx"
    resources: dict[str, int] = field(default_factory=dict)  # member name -> size


def _looks_like_workbook(data: bytes) -> bool:
    head = data[:4096].lstrip()
    return b"<workbook" in head[:2048] or head.startswith(b"<?xml")


def extract(path: str | Path, max_twb_bytes: int = MAX_TWB_BYTES) -> ExtractResult:
    """Workbook path -> `.twb` bytes and a map of the other members' sizes.

    `max_twb_bytes` caps the bytes *inflated* out of an archive, defaulting to
    `MAX_TWB_BYTES`. It is a parameter so a caller with a smaller appetite can
    say so, and so the limit is testable without a 256 MB fixture.
    """
    path = Path(path)
    if not path.is_file():
        raise InvalidWorkbookError(f"File not found: {path}")

    if zipfile.is_zipfile(path):
        return _extract_twbx(path, max_twb_bytes)

    data = path.read_bytes()
    if not _looks_like_workbook(data):
        raise InvalidWorkbookError(
            f"{path.name} is neither a .twbx archive nor a Tableau .twb XML file."
        )
    return ExtractResult(twb_bytes=data, source_format="twb")


def _read_capped(archive: zipfile.ZipFile, name: str, limit: int) -> bytes:
    """Inflate one member, refusing as soon as it passes `limit`.

    Incremental on purpose. `ZipFile.read()` decompresses the whole member and
    only then verifies the CRC, so a member that lies about its size is caught
    *after* the allocation it was supposed to prevent. Reading in chunks means
    the refusal costs one chunk more than the limit, whatever the file claims.

    The two defences cover different attacks, which is why both are here:

    * An **honest but enormous** member - a genuine multi-gigabyte `.twb` - is
      stopped by the cap. This is the only defence on the CLI and desktop paths,
      which never see the API's checks.
    * A **lying** member is stopped by the chunked read itself: `zipfile` bounds
      each read by the declared size, so a member claiming 4 KB yields 4 KB and
      then fails its CRC. The lie limits the damage, and the mismatch is
      reported as what it is rather than as a corrupt file, because an archive
      that misdescribes its own contents is a different problem from a damaged
      one and calls for a different response.
    """
    collected = bytearray()
    try:
        with archive.open(name) as member:
            while chunk := member.read(_CHUNK_BYTES):
                collected.extend(chunk)
                if len(collected) > limit:
                    raise InvalidWorkbookError(
                        f"The workbook inside the archive is larger than this "
                        f"will open ({limit:,} bytes). It was not read. This is "
                        "a limit, not a damaged file - raise max_twb_bytes if "
                        "the workbook really is this large."
                    )
    except zipfile.BadZipFile as exc:
        raise InvalidWorkbookError(
            f"The archive's directory does not describe what it contains: "
            f"{name} does not match the size or checksum recorded for it. It "
            "was not opened. A file like this is either damaged in transit or "
            "built to be misread, and neither is safe to parse."
        ) from exc
    return bytes(collected)


def _extract_twbx(path: Path, max_twb_bytes: int = MAX_TWB_BYTES) -> ExtractResult:
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        # Top-level .twb members (no path separator), then any .twb as fallback.
        top_level = [i for i in infos if i.filename.endswith(".twb") and "/" not in i.filename]
        candidates = top_level or [i for i in infos if i.filename.endswith(".twb")]
        if not candidates:
            raise InvalidWorkbookError(f"No .twb found inside archive {path.name}.")
        if len(candidates) > 1:
            raise InvalidWorkbookError(
                f"Ambiguous archive: {len(candidates)} .twb files found in {path.name}."
            )

        twb_member = candidates[0]
        # Only this member is read, and only up to the cap.
        twb_bytes = _read_capped(zf, twb_member.filename, max_twb_bytes)
        # Record other members' *declared* sizes WITHOUT reading their bytes.
        # Declared, because these come from the archive's own directory and
        # nothing here verifies them; they are a manifest, not a measurement.
        resources = {
            i.filename: i.file_size
            for i in infos
            if i.filename != twb_member.filename
        }

    if not _looks_like_workbook(twb_bytes):
        raise InvalidWorkbookError(
            f"The .twb inside {path.name} does not look like a Tableau workbook."
        )
    return ExtractResult(
        twb_bytes=twb_bytes, source_format="twbx", resources=resources
    )
