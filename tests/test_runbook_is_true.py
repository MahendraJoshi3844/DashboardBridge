"""The operator runbook says only things the code actually does.

A runbook is the one document a customer follows literally, at the moment they
are least able to work around a mistake in it - a new install, often air-gapped,
usually under time pressure. A variable named wrongly there is not a typo; it is
an afternoon of someone's life, and the deployment silently running on defaults
while they believe they configured it.

The first draft of `RUNBOOK.md` said `SECRET_PROVIDER`. The code reads
`SECRETS_PROVIDER`. Nothing would have failed - the deployment would have
quietly used the environment backend while the operator believed their vault was
in play, which is the exact failure `P7.2` was built to prevent, reintroduced
through documentation.

So every environment variable and every command the runbook names is checked
against the source. This does not prove the prose is right; it proves the names
are, which is the part a person copies without reading.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "operations" / "RUNBOOK.md"

#: Variables the runbook names that are *not* read by this codebase, with the
#: reason. Empty by intent - an entry here is a claim that needs one.
NOT_OURS: dict[str, str] = {}


def _searchable_source() -> str:
    roots = (ROOT / "engines", ROOT / "apps" / "api" / "app", ROOT / "packages")
    return "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for root in roots
        if root.exists()
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )


@pytest.fixture(scope="module")
def runbook() -> str:
    assert RUNBOOK.is_file(), f"{RUNBOOK} is missing"
    return RUNBOOK.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def source() -> str:
    return _searchable_source()


def test_every_environment_variable_it_names_is_one_we_read(runbook, source):
    """The check that would have caught `SECRET_PROVIDER`."""
    named = {
        match.group(0)
        for match in re.finditer(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){1,4}\b", runbook)
    }
    # Words that look like variables and are prose or values, not settings.
    prose = {
        "NOT_SCANNED",
        "PRIVACY_MODE",  # checked below with its values
    }
    missing = sorted(
        name
        for name in named - prose - set(NOT_OURS)
        if f'"{name}"' not in source and f"'{name}'" not in source
    )
    assert missing == [], (
        f"{missing} are named in the runbook and read nowhere in the code. "
        "Either the name is wrong or the setting does not exist."
    )


def test_the_privacy_modes_it_lists_are_the_ones_that_exist(runbook):
    from dashboardbridge_contracts.enums import PrivacyMode

    for mode in PrivacyMode:
        assert f"PRIVACY_MODE={mode.value}" in runbook, mode.value


def test_the_providers_it_documents_are_the_ones_that_exist(runbook):
    """Both options, because the customer picks on what their environment has.

    A runbook that documents one of two providers is a customer who does not
    know the other exists.
    """
    from dashboardbridge_contracts.enums import ProviderKind

    for kind in ProviderKind:
        if kind is ProviderKind.NONE:
            continue
        assert f"AI_PROVIDER={kind.value}" in runbook, kind.value


def test_every_licence_command_it_gives_is_one_the_cli_accepts(runbook):
    """The commands are copied verbatim by whoever follows this."""
    from engines.licensing.cli import _parser

    parser = _parser()
    subcommands = {
        name
        for action in parser._subparsers._group_actions  # noqa: SLF001
        for name in action.choices
    }
    for command in re.findall(r"t2pbi-license (\w+)", runbook):
        assert command in subcommands, command

    # And every long option, since a wrong flag is the same afternoon lost.
    for command in subcommands:
        block = re.search(
            rf"t2pbi-license {command}\b(.*?)```", runbook, re.S
        )
        if block is None:
            continue
        declared = {
            option
            for action in parser._subparsers._group_actions  # noqa: SLF001
            for action_ in action.choices[command]._actions  # noqa: SLF001
            for option in action_.option_strings
        }
        for flag in re.findall(r"(?<![\w-])--[a-z-]+", block.group(1)):
            assert flag in declared, f"{command} has no {flag}"


def test_it_states_the_limits_rather_than_leaving_them_to_be_discovered(runbook):
    """The three things a customer would otherwise report as bugs.

    Each is a deliberate position, and each looks like a defect until someone
    says out loud that it is not.
    """
    limits = runbook[runbook.index("## Known limits") :]
    assert "Filters are reported, not converted" in limits
    assert "schema, no rows" in limits
    assert "Tableau Desktop" in limits


def test_it_does_not_claim_the_ai_path_has_been_run_against_a_real_model(runbook):
    """The one claim it would be most tempting to soften.

    Every AI path in this product goes through `MockProvider`. A runbook that
    reads as though the feature is proven sends a customer to configure it with
    an expectation nobody has earned.
    """
    assert "MockProvider" in runbook
    assert "not been verified" in runbook or "Not yet verified" in runbook
