"""Accounts, sessions and seats (`P7.1`).

The deployment runs on the customer's premises and its users are their own
people - developers and analysts converting workbooks in both directions. There
is no vendor-side directory to authenticate against, so accounts are local, and
an air-gapped customer must still be able to add a colleague on a Tuesday.

`engines/identity` owns the cryptography and knows nothing about storage. This
module owns the decisions that need a database and a licence.

## One privilege, not a role vocabulary

Everyone converts. An admin may additionally add and deactivate people. Viewer /
editor / owner would be a guess about a permission model nobody has asked for,
and permission models are very hard to take away once a customer has configured
one - so the vocabulary stays at the one distinction that has a reason to exist.

## Seats are the licence's, and they mean active users

`License.seats` was carried and never consulted, which makes it decoration. It
is enforced here, counting *active* users: deactivating a leaver frees the seat
at once, because charging a customer for people who have left punishes them for
tidying up.

## Two clocks on a session

`expires_at` is absolute, so a session ends eventually whatever the user does.
`last_seen_at` drives an idle cutoff, which is what closes the laptop nobody
came back to. Absolute expiry alone leaves a browser on a shared machine signed
in for the whole window; idle alone never ends a session someone keeps poking.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.core.licensing import status
from app.db.models import Session, User, UserProduct
from engines.conversion.directions import ENGINE_FEATURES
from engines.identity import (
    hash_password,
    needs_rehash,
    new_session_token,
    session_digest,
    verify_password,
)

#: How long a session can live at all.
SESSION_LIFETIME = timedelta(hours=12)
#: How long it can go unused inside that.
IDLE_TIMEOUT = timedelta(hours=2)

#: The cookie the browser holds. `httpOnly` so no script can read it, which
#: removes token theft by injection as a class rather than mitigating it.
COOKIE_NAME = "dbb_session"


class AccountError(Exception):
    """Something an account operation will not do. Carries a status and a sentence."""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class EmailTaken(AccountError):
    status_code = 409


class NoSeatsLeft(AccountError):
    #: 402, the same code the conversion gate uses. Both are "your licence does
    #: not cover this", and a client that handles one should handle the other.
    status_code = 402


class LastAdministrator(AccountError):
    status_code = 409


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes; compare in UTC either way.

    Without this an expiry check silently compares naive to aware and raises,
    which surfaces as a 500 on a perfectly ordinary request.
    """
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def find_by_email(session: DbSession, email: str) -> User | None:
    """Case-insensitive. People type their own address however they like, and
    an account they cannot get into is a support call."""
    return session.scalar(
        select(User).where(func.lower(User.email) == email.strip().lower())
    )


def active_user_count(session: DbSession) -> int:
    return session.scalar(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    )


def seats_available(session: DbSession) -> int | None:
    """Seats left, or `None` when the licence does not say.

    An unlicensed deployment cannot convert at all, so it is not the place to
    also argue about headcount; the conversion gate is the lever.
    """
    current = status()
    if current.license is None or not current.license.seats:
        return None
    return current.license.seats - active_user_count(session)


class UnknownProduct(AccountError):
    status_code = 422


def licensed_products() -> set[str]:
    """The products the licence includes (all of them when it names none)."""
    licence = status().license
    named = set(licence.features) & ENGINE_FEATURES if licence is not None else set()
    return named or set(ENGINE_FEATURES)


def set_products(user: User, products: list[str] | set[str]) -> None:
    """Replace what this person may use. Unknown names are refused, not dropped."""
    wanted = {p.strip().lower() for p in products if p.strip()}
    unknown = sorted(wanted - ENGINE_FEATURES)
    if unknown:
        raise UnknownProduct(
            f"Unknown product {', '.join(unknown)}. The products are: {', '.join(sorted(ENGINE_FEATURES))}."
        )
    keep = [g for g in user.product_grants if g.product in wanted]
    have = {g.product for g in keep}
    user.product_grants = keep + [UserProduct(product=p) for p in sorted(wanted - have)]


def create_user(
    session: DbSession,
    *,
    email: str,
    display_name: str,
    password: str,
    is_admin: bool = False,
    enforce_seats: bool = True,
    products: list[str] | None = None,
) -> User:
    """Add a person. Raises `AccountError` for anything it will not do.

    `enforce_seats` is off only for the bootstrap administrator: refusing to
    create the very first account because a licence has not been installed yet
    is a deployment nobody can get into to install one.
    """
    email = email.strip()
    if find_by_email(session, email) is not None:
        raise EmailTaken(f"{email} already has an account on this deployment.")

    if enforce_seats:
        left = seats_available(session)
        if left is not None and left <= 0:
            seats = status().license.seats
            raise NoSeatsLeft(
                f"This licence covers {seats} active users and {seats} are "
                "already active. Deactivate someone who has left, or ask for a "
                "licence with more seats."
            )

    # Raises `PasswordTooWeak`, which the route turns into a 422 carrying the
    # rule. Deliberately not caught here: a weak password is not an account
    # that exists with a bad password, it is an account that was never made.
    user = User(
        email=email,
        display_name=display_name,
        password_hash=hash_password(password),
        is_admin=is_admin,
    )
    set_products(user, licensed_products() if products is None else products)
    session.add(user)
    session.flush()
    return user


def deactivate(session: DbSession, user: User, *, acting_as: User) -> None:
    """Stop someone signing in, and end the sessions they already have.

    Both halves matter. Without the second, a leaver keeps working until their
    cookie happens to expire, which can be most of a day.
    """
    if user.user_id == acting_as.user_id:
        raise LastAdministrator(
            "You cannot deactivate your own account. A deployment with no "
            "active administrator can only be repaired on the machine itself."
        )
    remaining = session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.is_active.is_(True), User.is_admin.is_(True), User.user_id != user.user_id)
    )
    if user.is_admin and not remaining:
        raise LastAdministrator(
            "This is the only active administrator. Make someone else an "
            "administrator first."
        )
    user.is_active = False
    _revoke_all(session, user)


def _revoke_all(session: DbSession, user: User) -> None:
    for row in session.scalars(
        select(Session).where(Session.user_id == user.user_id, Session.revoked_at.is_(None))
    ):
        row.revoked_at = _now()


def sign_in(session: DbSession, *, email: str, password: str) -> tuple[User, str] | None:
    """`(user, token)`, or `None` for every kind of failure.

    One `None` rather than distinct results on purpose. "No such address",
    "wrong password" and "that account is deactivated" must be indistinguishable
    to the caller, because a login form that can tell them apart is a list of
    who works here.

    The password is verified even when the address is unknown, against a hash
    that cannot match, so that the answer takes the same work either way - the
    timing is otherwise as good as a reply.
    """
    user = find_by_email(session, email)
    stored = user.password_hash if user is not None else _DUMMY_HASH
    matched = verify_password(password, stored)

    if user is None or not matched or not user.is_active:
        return None

    if needs_rehash(user.password_hash):
        # The one moment the plaintext is legitimately in hand.
        user.password_hash = hash_password(password)

    token = new_session_token()
    now = _now()
    session.add(
        Session(
            user_id=user.user_id,
            token_digest=session_digest(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + SESSION_LIFETIME,
        )
    )
    user.last_login_at = now
    return user, token


def user_for_token(session: DbSession, token: str | None) -> User | None:
    """The signed-in user, or `None`. Touches `last_seen_at` on success.

    Every refusal path returns `None` and none of them raise: an expired
    session, a revoked one, a token for a user who has since been deactivated,
    a forged string, no cookie at all. A caller that has to distinguish them is
    a caller that will get one of them wrong.
    """
    if not token:
        return None
    row = session.scalar(
        select(Session).where(Session.token_digest == session_digest(token))
    )
    if row is None or row.revoked_at is not None:
        return None

    now = _now()
    if _aware(row.expires_at) <= now or _aware(row.last_seen_at) + IDLE_TIMEOUT <= now:
        return None

    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        return None

    row.last_seen_at = now
    return user


def sign_out(session: DbSession, token: str | None) -> None:
    if not token:
        return
    row = session.scalar(
        select(Session).where(Session.token_digest == session_digest(token))
    )
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()


def bootstrap_admin(session: DbSession) -> User | None:
    """The first administrator, from the environment, on an empty deployment.

    The same shape as installing a licence: set it where the process reads it
    and restart. There is deliberately **no route** that creates the first
    admin - an endpoint that makes one when the table is empty makes one on any
    deployment whose database has not finished migrating.

    Does nothing once anyone exists, so a variable left in a compose file
    cannot re-create an administrator that somebody deliberately removed. The
    password goes through the same rule as every other; a convenience path that
    skips it is exactly where the weak password lives.
    """
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    if not email or not password:
        return None
    if session.scalar(select(func.count()).select_from(User)):
        return None
    return create_user(
        session,
        email=email,
        display_name=email.split("@", 1)[0],
        password=password,
        is_admin=True,
        enforce_seats=False,
    )


#: A real hash of a value nobody has, so an unknown address costs the same
#: scrypt work as a known one. Computed once at import rather than per request.
_DUMMY_HASH = hash_password("this password opens no account at all")
