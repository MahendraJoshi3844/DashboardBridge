"""What the extractor will inflate (`P7.3`, `P7.4`).

`inspect_zip_archive` in the API reads a zip's central directory and refuses a
bomb "by its own declaration before a single byte is inflated". That is true and
it is not enough, for two reasons found by measuring rather than by reading.

**A central directory is written by whoever made the file.** Rewriting a 200 MB
member's `file_size` fields to say `4096` produces an archive that passes all
four declaration-based caps - 4 KB declared, ratio 0.0 - and still holds 200 MB
of deflate stream. Nothing in the declaration has to be true.

**`ZipFile.read()` inflates the whole member before the check that catches it.**
Measured: **459 MB of peak allocation from a 204 kB file**, and only then a
`BadZipFile` for a CRC that can be verified only at the end. The exception
arrives after the memory is spent, which is the wrong order for a defence.

The fix reads the member in chunks against a cap, and the two halves turn out to
stop different attacks - which the probe showed and the first draft of these
tests got wrong:

* An **honest but enormous** member is stopped by the cap.
* A **lying** member is stopped by the chunked read itself. `zipfile` bounds
  each read by the declared size, so a member claiming 4 KB yields 4 KB and then
  fails its CRC: the lie limits the damage. What was missing was not a bound but
  a *message* - it surfaced as `BadZipFile`, "Bad CRC-32", which reads as a
  damaged file and sends someone to re-save a workbook that is fine.

**And the API is not always there.** `extract()` is what the CLI and the desktop
shell call, and neither goes near `inspect_zip_archive`. For those two paths the
cap is the only limit there is.
"""

from __future__ import annotations

import struct
import tracemalloc
import zipfile
from pathlib import Path

import pytest

from engines.t2pbi.core.extract import (
    MAX_TWB_BYTES,
    InvalidWorkbookError,
    extract,
)

WORKBOOK = b"<?xml version='1.0'?><workbook version='18.1'><datasources/></workbook>"


def _archive(path: Path, payload: bytes, *, declare: int | None = None) -> Path:
    """A `.twbx` holding one `.twb`, optionally lying about how big it is."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("book.twb", payload)
    if declare is None:
        return path
    raw = path.read_bytes().replace(
        struct.pack("<I", len(payload)), struct.pack("<I", declare)
    )
    liar = path.with_name("liar.twbx")
    liar.write_bytes(raw)
    return liar


# --- the ordinary case ----------------------------------------------------------


def test_a_workbook_within_the_limit_still_extracts(tmp_path):
    """A cap that costs the product its normal input is not a fix."""
    path = _archive(tmp_path / "ok.twbx", WORKBOOK + b"<!-- " + b"x" * 10_000 + b" -->")
    assert b"<workbook" in extract(path).twb_bytes


def test_a_plain_twb_is_unaffected(tmp_path):
    """Nothing is inflated, so nothing is capped."""
    path = tmp_path / "plain.twb"
    path.write_bytes(WORKBOOK)
    assert extract(path).source_format == "twb"


# --- the cap --------------------------------------------------------------------


def test_a_member_that_inflates_past_the_cap_is_refused(tmp_path):
    payload = WORKBOOK + b"A" * (4 * 1024 * 1024)
    path = _archive(tmp_path / "big.twbx", payload)

    with pytest.raises(InvalidWorkbookError) as raised:
        extract(path, max_twb_bytes=1024 * 1024)

    assert "1" in str(raised.value)


def test_the_refusal_says_it_is_a_limit_rather_than_a_broken_file(tmp_path):
    """The two are different problems with different actions, and a wrong
    message sends someone to re-save a workbook that is fine."""
    path = _archive(tmp_path / "big.twbx", WORKBOOK + b"A" * (4 * 1024 * 1024))

    with pytest.raises(InvalidWorkbookError) as raised:
        extract(path, max_twb_bytes=1024 * 1024)

    message = str(raised.value).lower()
    assert "larger" in message or "limit" in message
    assert "corrupt" not in message


def test_a_lying_central_directory_is_refused_as_a_mismatch_not_a_broken_file(
    tmp_path,
):
    """The case the declaration-based check cannot see.

    The archive says 4096 bytes and contains four megabytes. `zipfile` bounds
    the read by the declaration, so the lie limits its own damage and the CRC
    then fails - but it failed as `BadZipFile`, "Bad CRC-32", which reads as a
    damaged file. An archive that misdescribes its own contents is a different
    problem from a damaged one, and only one of the two is worth re-saving.
    """
    payload = WORKBOOK + b"A" * (4 * 1024 * 1024)
    path = _archive(tmp_path / "bomb.twbx", payload, declare=4096)

    with pytest.raises(InvalidWorkbookError) as raised:
        extract(path, max_twb_bytes=1024 * 1024)

    message = str(raised.value).lower()
    assert "does not describe" in message or "does not match" in message


def test_a_zipfile_error_never_escapes_the_extractor(tmp_path):
    """Callers handle `InvalidWorkbookError`; nothing handles `BadZipFile`.

    A `zipfile` exception reaching the API becomes a 500 for what is in fact a
    refusable input, and reaching the CLI becomes a traceback.
    """
    path = _archive(tmp_path / "bomb.twbx", WORKBOOK + b"A" * 200_000, declare=512)

    with pytest.raises(InvalidWorkbookError):
        extract(path)


def test_the_cap_bounds_what_is_actually_allocated(tmp_path):
    """The measurement the fix exists for.

    Before it, `ZipFile.read()` on a 204 kB archive reached 459 MB of peak
    allocation and *then* raised. Asserting only that something raises would
    pass either way, so this asserts the memory - the thing that was wrong.
    """
    payload = WORKBOOK + b"A" * (64 * 1024 * 1024)
    path = _archive(tmp_path / "bomb.twbx", payload, declare=4096)
    cap = 1024 * 1024

    tracemalloc.start()
    try:
        with pytest.raises(InvalidWorkbookError):
            extract(path, max_twb_bytes=cap)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert peak < cap * 8, f"{peak / 1e6:.1f} MB peaked for a {cap / 1e6:.1f} MB cap"


def test_an_honest_but_enormous_member_is_stopped_by_the_cap(tmp_path):
    """The half the chunked read cannot do.

    A member that tells the truth about being huge is read exactly as asked, so
    only the cap stops it - and on the CLI and desktop paths the cap is the only
    thing in the way at all.
    """
    payload = WORKBOOK + b"A" * (8 * 1024 * 1024)
    path = _archive(tmp_path / "honest.twbx", payload)
    cap = 1024 * 1024

    tracemalloc.start()
    try:
        with pytest.raises(InvalidWorkbookError) as raised:
            extract(path, max_twb_bytes=cap)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()

    assert "larger" in str(raised.value)
    assert peak < cap * 8, f"{peak / 1e6:.1f} MB peaked for a {cap / 1e6:.1f} MB cap"


def test_the_default_cap_is_stated_rather_than_implied():
    """A limit nobody can find is one nobody can raise when a real workbook
    needs it."""
    assert MAX_TWB_BYTES > 0
    assert extract.__doc__ and "max_twb_bytes" in extract.__doc__


def test_the_engine_refuses_without_the_api_having_checked(tmp_path):
    """`extract()` is what the CLI and desktop shell call.

    Neither goes near `inspect_zip_archive`, so a limit that lived only at the
    HTTP boundary would leave both unprotected - which is what this test is
    here to keep true.
    """
    import inspect

    from engines.t2pbi.core import extract as module

    source = inspect.getsource(module)
    assert "inspect_zip_archive" not in source
    path = _archive(tmp_path / "bomb.twbx", WORKBOOK + b"A" * (4 * 1024 * 1024))
    with pytest.raises(InvalidWorkbookError):
        extract(path, max_twb_bytes=1024 * 1024)
