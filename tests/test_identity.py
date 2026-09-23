"""Passwords and sessions (`P7.1`).

The deployment runs on the customer's own machines and its users are their
people - developers and analysts converting workbooks, some of whom know
Tableau, some Power BI, most neither in depth. They need accounts of their own:
whose conversion this was is the question every other question hangs off.

## Why this is stdlib and not a library

`hashlib.scrypt` rather than bcrypt or argon2. Not because it is better - argon2
is - but because this product ships into air-gapped environments, and every
dependency is something a customer's security team has to vet and something that
has to be present on a machine with no index to install from. scrypt is
memory-hard, it is in the standard library, and the parameters are recorded in
the stored hash so they can be raised later without invalidating a single
existing password.

## What the tests are guarding

Two failures here are silent and total. A verifier that accepts an empty or
malformed stored hash turns a corrupt row into a skeleton key. A session token
stored in the clear turns a database read into every live session. Both look
completely ordinary in review, and neither shows up in a passing login.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from engines.identity import (
    PasswordTooWeak,
    hash_password,
    needs_rehash,
    new_session_token,
    session_digest,
    verify_password,
)

PASSWORD = "correct horse battery staple"


# --- hashing -----------------------------------------------------------------


def test_a_password_verifies_against_its_own_hash():
    assert verify_password(PASSWORD, hash_password(PASSWORD)) is True


def test_a_wrong_password_does_not():
    assert verify_password("wrong", hash_password(PASSWORD)) is False


def test_the_same_password_hashes_differently_every_time():
    """Salt. Two users choosing the same password must not be visibly the same
    in the table, and a rainbow table must be useless."""
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_the_stored_hash_is_never_the_password_or_a_plain_digest():
    import hashlib

    stored = hash_password(PASSWORD)
    assert PASSWORD not in stored
    assert hashlib.sha256(PASSWORD.encode()).hexdigest() not in stored


def test_the_parameters_are_recorded_so_they_can_be_raised_later():
    """A cost factor baked into code instead of into the hash is a cost factor
    nobody can ever raise: the day you do, every existing password stops
    verifying."""
    stored = hash_password(PASSWORD)
    assert stored.startswith("scrypt$")
    assert "n=" in stored and "r=" in stored and "p=" in stored


def test_a_hash_made_with_weaker_parameters_still_verifies():
    """The point of recording them. An old password keeps working, and
    `needs_rehash` is how it gets upgraded on the owner's next login."""
    weak = hash_password(PASSWORD, n=2**10)
    assert verify_password(PASSWORD, weak) is True
    assert needs_rehash(weak) is True
    assert needs_rehash(hash_password(PASSWORD)) is False


# --- the refusals that matter -------------------------------------------------


@pytest.mark.parametrize(
    "stored",
    [
        "",
        "   ",
        "not-a-hash",
        "scrypt$",
        "scrypt$n=16384,r=8,p=1$",
        "scrypt$n=16384,r=8,p=1$salt",
        "argon2$whatever$salt$hash",
        "scrypt$n=0,r=8,p=1$c2FsdA==$aGFzaA==",
        None,
    ],
)
def test_a_stored_hash_that_is_not_one_never_verifies(stored):
    """The skeleton key.

    An empty or truncated column, a row half-written by a failed migration, a
    hash from a scheme this build does not have - every one of them must be a
    refusal. A verifier that returns True for any of these authenticates
    everybody, and the login screen looks completely normal while it does.
    """
    assert verify_password(PASSWORD, stored) is False
    assert verify_password("", stored) is False


def test_an_empty_password_is_refused_at_the_point_it_is_set():
    """Refused when chosen, not quietly hashed. A blank password that hashes
    successfully is an account anyone can open by pressing enter."""
    with pytest.raises(PasswordTooWeak):
        hash_password("")


def test_a_short_password_is_refused_and_the_rule_is_in_the_message():
    """"Too weak" without the rule sends someone guessing. The number is in the
    sentence so the next attempt can succeed."""
    with pytest.raises(PasswordTooWeak) as refusal:
        hash_password("short")
    assert "12" in str(refusal.value)


def test_a_very_long_password_is_not_silently_truncated():
    """bcrypt's 72-byte cut is the classic version of this: two different long
    passwords that both open the account. scrypt has no such limit, and this
    asserts the wrapper did not add one."""
    base = "x" * 200
    assert verify_password(base + "a", hash_password(base + "a")) is True
    assert verify_password(base + "b", hash_password(base + "a")) is False


def test_the_comparison_is_constant_time():
    """Asserted on the source, because timing cannot be tested reliably here.

    A byte-by-byte `==` on a digest leaks how much of it was right. That is a
    slow attack and a real one, and it is one character of difference in code
    that reads identically either way.
    """
    tree = ast.parse(inspect.getsource(verify_password))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "compare_digest" in called


# --- sessions ----------------------------------------------------------------


def test_a_session_token_is_long_and_unpredictable():
    token = new_session_token()
    assert len(token) >= 32
    assert len({new_session_token() for _ in range(50)}) == 50


def test_the_token_is_stored_as_a_digest_and_not_as_itself():
    """A database read must not be a set of live sessions.

    Password hashing is universally remembered and session storage routinely is
    not, which is odd: a stolen session token needs no cracking at all.
    """
    token = new_session_token()
    stored = session_digest(token)
    assert token not in stored
    assert stored == session_digest(token), "must be stable, or no lookup works"
    assert session_digest(new_session_token()) != stored


def test_the_session_digest_is_not_a_password_hash():
    """Deliberately different, and worth saying why.

    A session token is 256 bits of randomness, so it needs no salt and no work
    factor - a fast digest is correct, and using scrypt here would make every
    request pay a password's cost for nothing.
    """
    assert not session_digest(new_session_token()).startswith("scrypt$")


# --- the boundary -------------------------------------------------------------


def test_this_layer_knows_nothing_about_storage_or_http():
    """`engines/` never imports the app (the layering rule this repo runs on).

    Identity logic that reaches for a session or a request is identity logic
    that can only be tested through one, which is how the checks above stop
    being written.
    """
    root = Path(__file__).resolve().parents[1]
    source = (root / "engines" / "identity" / "__init__.py").read_text("utf-8")
    tree = ast.parse(source)
    imported = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    forbidden = [
        name
        for name in imported
        if name.startswith(("app", "fastapi", "sqlalchemy", "starlette"))
    ]
    assert forbidden == [], forbidden
