"""Passwords and session tokens (`P7.1`).

Pure: no database, no request, no framework. The deployment's storage and its
routes live in `apps/api`, and this is the part that has to be right whatever
they do - which is also the part that can be tested without either.

## scrypt, from the standard library

Not because it beats argon2 - it does not - but because this product ships into
air-gapped environments. Every dependency is something a customer's security
team has to vet and something that must already be present on a machine with no
package index to reach. `hashlib.scrypt` is memory-hard, it has been in the
standard library since 3.6, and it needs nothing installed.

The parameters are written into the stored hash. A cost factor baked into code
instead cannot ever be raised: the day you raise it, every existing password
stops verifying. Recorded, an old hash keeps working and `needs_rehash` tells
the caller to re-store it the next time it has the plaintext - which is the one
moment it legitimately does.

## The two silent failures this file exists to avoid

**A verifier that accepts a stored value that is not a hash.** An empty column,
a row half-written by a failed migration, a hash from a scheme this build does
not carry: each must be a refusal. One that returns `True` authenticates
everybody, and the login screen looks completely normal while it does.

**A session token stored in the clear.** Password hashing is universally
remembered and session storage routinely is not, which is backwards - a stolen
session token needs no cracking at all. Only a digest is stored, so reading the
table gets you nothing you can present.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

#: Refused below this. Long enough to matter, short enough that people do not
#: write it on a card - and stated in the refusal, because "too weak" without
#: the rule just sends someone guessing.
MINIMUM_PASSWORD_LENGTH = 12

#: scrypt cost. `n` is the memory/CPU factor; 2**15 with r=8 is about 32 MB per
#: hash, which is a deliberate cost on a login and a prohibitive one on a
#: dictionary. Raise `n` here and existing hashes keep verifying - that is what
#: recording it in the stored string buys.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32

#: 256 bits. Guessing is not an attack on this; losing it is.
_TOKEN_BYTES = 32


def _maxmem(n: int, r: int) -> int:
    """The memory ceiling to hand OpenSSL, derived from the cost itself.

    OpenSSL refuses scrypt above 32 MB unless told otherwise, and the chosen
    cost deliberately exceeds that - being expensive in memory is the whole
    point of the algorithm. Computing the ceiling from `n` and `r` rather than
    fixing a constant means raising the cost later does not also require
    remembering to raise a second unrelated number, which is exactly the kind of
    pair that gets out of step.

    scrypt needs about `128 * n * r` bytes; the megabyte on top is headroom for
    the implementation's own overhead.
    """
    return 128 * n * r + (1 << 20)


_SCHEME = "scrypt"


class PasswordTooWeak(ValueError):
    """A password refused at the moment it is chosen, not quietly accepted."""


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(
    password: str,
    *,
    n: int = SCRYPT_N,
    r: int = SCRYPT_R,
    p: int = SCRYPT_P,
) -> str:
    """A storable hash, self-describing.

    `scrypt$n=32768,r=8,p=1$<salt>$<key>` - scheme, parameters, salt and key,
    so a future build with a higher cost can read this one.
    """
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        raise PasswordTooWeak(
            f"A password must be at least {MINIMUM_PASSWORD_LENGTH} characters. "
            "A passphrase of a few unrelated words is easier to remember and "
            "much harder to guess than a short one with punctuation in it."
        )
    salt = secrets.token_bytes(_SALT_BYTES)
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=_maxmem(n, r),
        dklen=_KEY_BYTES,
    )
    return f"{_SCHEME}$n={n},r={r},p={p}${_b64(salt)}${_b64(key)}"


def _parsed(stored: object) -> tuple[int, int, int, bytes, bytes] | None:
    """`(n, r, p, salt, key)`, or `None` if this is not a hash we can read.

    Every failure path returns `None`. The one thing this must never do is fall
    through to a comparison with a default, an empty salt or a zero cost.
    """
    if not isinstance(stored, str):
        return None
    parts = stored.split("$")
    if len(parts) != 4:
        return None
    scheme, parameters, salt_text, key_text = parts
    if scheme != _SCHEME:
        return None
    try:
        values = dict(
            item.split("=", 1) for item in parameters.split(",") if "=" in item
        )
        n, r, p = int(values["n"]), int(values["r"]), int(values["p"])
        salt = base64.b64decode(salt_text, validate=True)
        key = base64.b64decode(key_text, validate=True)
    except (KeyError, ValueError, TypeError):
        return None
    # scrypt requires n to be a power of two above 1; a zero or one here is not
    # a weak hash, it is a hash that cannot be recomputed, so it is not one.
    #
    # Restating a rule rather than adding one: `hashlib.scrypt` raises on these
    # and `verify_password` catches it, so removing this changes no outcome -
    # verified by removing it and watching nothing fail. It stays because the
    # contract of `_parsed` is "parameters that can actually be computed", and
    # a caller reading it should not have to know which exception proves that.
    if n < 2 or n & (n - 1) or r < 1 or p < 1 or not salt or not key:
        return None
    return n, r, p, salt, key


def verify_password(password: str, stored: object) -> bool:
    """Does `password` match `stored`? Never raises; anything unreadable is False."""
    parsed = _parsed(stored)
    if parsed is None:
        return False
    n, r, p, salt, key = parsed
    try:
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            maxmem=_maxmem(n, r),
            dklen=len(key),
        )
    except ValueError:
        # Parameters that parse but that this platform will not compute - an
        # `n` above the memory limit, say. Not a match.
        return False
    # `compare_digest`, not `==`. A byte-by-byte comparison leaks how much of
    # the digest was right through timing; that is a slow attack and a real
    # one, and the two spellings read identically.
    return hmac.compare_digest(candidate, key)


def needs_rehash(stored: object, *, n: int = SCRYPT_N) -> bool:
    """Was this hashed with a cost below what is current?

    True also for something unreadable: a row that cannot be verified should be
    replaced the moment the plaintext is available, not left in place.
    """
    parsed = _parsed(stored)
    if parsed is None:
        return True
    return parsed[0] < n


def new_session_token() -> str:
    """A session token. Given to the browser, never stored as it is."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def session_digest(token: str) -> str:
    """What the deployment stores for a session.

    A plain SHA-256, deliberately, and the difference from `hash_password`
    matters: a session token is 256 bits of randomness this code generated, so
    it needs no salt and no work factor. Using scrypt here would make every
    single request pay a password's cost for nothing, and the usual reason to
    pay it - that people choose guessable passwords - does not apply to
    something nobody chose.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


__all__ = [
    "MINIMUM_PASSWORD_LENGTH",
    "PasswordTooWeak",
    "hash_password",
    "needs_rehash",
    "new_session_token",
    "session_digest",
    "verify_password",
]
