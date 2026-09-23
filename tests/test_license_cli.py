"""The vendor's side of licensing (`P7.1`).

`engines/licensing` can mint and check a licence; nothing could *run* it. That
is not a small gap for a product whose commercial model is "the customer runs it
on their own machines and renews when it lapses" - issuing a licence was a
Python session, and a step that has to be improvised is a step that gets
improvised differently each time.

## The guard that matters more than the feature

The private key ends the scheme for every customer at once if it leaks, and
`tests/test_licensing.py` already fails the build if one is committed. That is
the last line, not the first: it catches the mistake after it has been made and
only if someone runs the suite before pushing.

So `keygen` refuses to *write* a private key anywhere inside a git work tree at
all. A tool that cannot put the key in the repository is a stronger guarantee
than a test that notices afterwards, and it costs one line of the operator's
attention rather than a revocation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from engines.licensing import LicenseInvalid, verify
from engines.licensing.cli import main

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> int:
    return main(list(args))


@pytest.fixture
def vendor(tmp_path, capsys):
    """A keypair in a directory that is not a git work tree."""
    out = tmp_path / "vendor"
    assert _run("keygen", "--out", str(out)) == 0
    capsys.readouterr()
    return out


# --- keygen ------------------------------------------------------------------


def test_keygen_writes_both_halves(vendor):
    assert (vendor / "vendor-private.pem").is_file()
    assert (vendor / "vendor-public.pem").is_file()
    assert "PRIVATE KEY" in (vendor / "vendor-private.pem").read_text()


def test_keygen_refuses_to_write_inside_this_repository(capsys):
    """The structural half of "never commit a private key".

    A test that fails once the key is already in the working tree catches the
    mistake after it has been made. Refusing to create it there means the
    mistake needs a deliberate second action.
    """
    assert _run("keygen", "--out", str(ROOT / "engines")) != 0
    assert "git" in capsys.readouterr().err.lower()
    assert not (ROOT / "engines" / "vendor-private.pem").exists()


def test_keygen_refuses_to_overwrite_an_existing_key(vendor, capsys):
    """Overwriting the vendor key does not lose one licence, it orphans every
    licence ever issued - none of them verify against the new public half."""
    assert _run("keygen", "--out", str(vendor)) != 0
    assert "already" in capsys.readouterr().err.lower()


def test_keygen_never_prints_the_private_key(tmp_path, capsys):
    out = tmp_path / "quiet"
    _run("keygen", "--out", str(out))
    printed = capsys.readouterr()
    assert "PRIVATE KEY" not in printed.out + printed.err
    assert str(out / "vendor-private.pem") in printed.out


# --- issue -------------------------------------------------------------------


def test_an_issued_licence_verifies_against_the_public_half(vendor, tmp_path):
    token_file = tmp_path / "customer.lic"
    assert (
        _run(
            "issue",
            "--key",
            str(vendor / "vendor-private.pem"),
            "--customer",
            "Northwind BI",
            "--days",
            "365",
            "--features",
            "convert",
            "--seats",
            "5",
            "--out",
            str(token_file),
        )
        == 0
    )
    licence = verify(
        token_file.read_text().strip(),
        public_key=(vendor / "vendor-public.pem").read_text(),
        today=date.today(),
    )
    assert licence.customer == "Northwind BI"
    assert licence.seats == 5
    assert licence.allows("convert")


def test_the_same_inputs_mint_the_same_licence(vendor, tmp_path):
    """Determinism, for the same reason the converter has it: a licence that
    differed run to run could not be compared with the one already sent."""
    tokens = []
    for name in ("a.lic", "b.lic"):
        path = tmp_path / name
        _run(
            "issue",
            "--key",
            str(vendor / "vendor-private.pem"),
            "--customer",
            "Same",
            "--expires",
            "2027-01-31",
            "--issued",
            "2026-01-31",
            "--features",
            "convert",
            "--seats",
            "1",
            "--out",
            str(path),
        )
        tokens.append(path.read_text())
    assert tokens[0] == tokens[1]


def test_an_expiry_before_the_issue_date_is_a_message_not_a_traceback(
    vendor, tmp_path, capsys
):
    code = _run(
        "issue",
        "--key",
        str(vendor / "vendor-private.pem"),
        "--customer",
        "Backwards",
        "--issued",
        "2026-06-01",
        "--expires",
        "2026-01-01",
        "--features",
        "convert",
        "--seats",
        "1",
        "--out",
        str(tmp_path / "no.lic"),
    )
    assert code != 0
    assert "expire" in capsys.readouterr().err.lower()
    assert not (tmp_path / "no.lic").exists()


def test_a_licence_is_not_written_where_it_would_be_committed(vendor, capsys):
    """A licence is not as dangerous as a private key and is still a customer's
    paid credential; the repository is not where it goes."""
    assert (
        _run(
            "issue",
            "--key",
            str(vendor / "vendor-private.pem"),
            "--customer",
            "X",
            "--days",
            "30",
            "--features",
            "convert",
            "--seats",
            "1",
            "--out",
            str(ROOT / "engines" / "x.lic"),
        )
        != 0
    )
    assert not (ROOT / "engines" / "x.lic").exists()


# --- inspect -----------------------------------------------------------------


def test_inspect_reports_what_the_licence_says(vendor, tmp_path, capsys):
    token = tmp_path / "c.lic"
    _run(
        "issue",
        "--key", str(vendor / "vendor-private.pem"),
        "--customer", "Readable Ltd",
        "--days", "10",
        "--features", "convert,ai",
        "--seats", "3",
        "--out", str(token),
    )
    capsys.readouterr()
    assert (
        _run(
            "inspect",
            "--file", str(token),
            "--public-key", str(vendor / "vendor-public.pem"),
        )
        == 0
    )
    reported = json.loads(capsys.readouterr().out)
    assert reported["customer"] == "Readable Ltd"
    assert reported["features"] == ["ai", "convert"]
    assert reported["days_remaining"] == 10


def test_a_tampered_licence_is_reported_as_forged_and_not_as_expired(
    vendor, tmp_path, capsys
):
    """The order `verify` is careful about, surfaced.

    Telling someone their forged licence has run out sends them to renew
    something that was never valid.
    """
    token = tmp_path / "t.lic"
    _run(
        "issue",
        "--key", str(vendor / "vendor-private.pem"),
        "--customer", "Real Ltd",
        "--days", "10",
        "--features", "convert",
        "--seats", "1",
        "--out", str(token),
    )
    payload, _, signature = token.read_text().strip().partition(".")
    token.write_text(payload[:-4] + "AAAA." + signature)
    capsys.readouterr()

    assert (
        _run(
            "inspect",
            "--file", str(token),
            "--public-key", str(vendor / "vendor-public.pem"),
        )
        != 0
    )
    said = capsys.readouterr().err.lower()
    assert "expire" not in said


def test_inspect_of_an_expired_licence_says_so_and_still_reads_it(
    vendor, tmp_path, capsys
):
    """An operator inspecting an expired licence needs to see whose it was and
    when it ran out - which is exactly the conversation they are having."""
    token = tmp_path / "old.lic"
    yesterday = date.today() - timedelta(days=1)
    _run(
        "issue",
        "--key", str(vendor / "vendor-private.pem"),
        "--customer", "Lapsed Ltd",
        "--issued", str(yesterday - timedelta(days=30)),
        "--expires", str(yesterday),
        "--features", "convert",
        "--seats", "1",
        "--out", str(token),
    )
    capsys.readouterr()
    code = _run(
        "inspect",
        "--file", str(token),
        "--public-key", str(vendor / "vendor-public.pem"),
    )
    assert code != 0
    said = capsys.readouterr().err
    assert "Lapsed Ltd" in said
    assert str(yesterday) in said


# --- it is actually runnable --------------------------------------------------


def test_the_command_is_declared_as_a_console_script():
    """A tool nobody can run is a module. The vendor runs this on their own
    machine, so it has to exist as a command after `pip install -e .`"""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "t2pbi-license = " in text


def test_it_runs_as_a_module(tmp_path):
    """The path an operator actually takes before the package is installed."""
    result = subprocess.run(
        [sys.executable, "-m", "engines.licensing.cli", "keygen", "--out", str(tmp_path / "k")],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "k" / "vendor-public.pem").is_file()


def test_the_repository_still_carries_no_private_key():
    """Restated here as well as in `test_licensing.py`: this file creates
    private keys, and a fixture writing one into the tree by accident is
    precisely the failure it is guarding against."""
    for path in ROOT.rglob("*.pem"):
        if ".venv" in path.parts or "node_modules" in path.parts:
            continue
        assert "PRIVATE KEY" not in path.read_text(errors="ignore"), path
