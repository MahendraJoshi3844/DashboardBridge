"""Who is using this deployment (`P7.1`).

The product runs on the customer's premises and its users are their own people:
developers and analysts converting workbooks in both directions, some of whom
know Tableau, some Power BI, most neither in depth. Accounts are local to the
deployment, because that is what "runs in your environment" has to mean - there
is no vendor-side directory to authenticate against, and an air-gapped customer
must still be able to add a colleague on a Tuesday.

## The decisions this file pins down

**One privilege, not a role vocabulary.** Everyone converts; an admin may also
add and deactivate people. Inventing viewer/editor/owner before anyone has asked
would be a guess about a permission model, and permission models are very hard
to take away once a customer has configured one.

**Seats are the licence's, and they are enforced.** `License.seats` was carried
and never used, which makes it decoration. The count that matters is *active*
users, so deactivating a leaver frees their seat immediately - the alternative
punishes the customer for tidying up.

**The first account is made by an operator, not over HTTP.** Installing a
licence is putting a file on the machine and restarting; so is creating the
first administrator. An endpoint that creates an admin when the table is empty
is an endpoint that creates an admin on any deployment whose database has not
finished migrating.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

PREFIX = "/api/v1"
GOOD_PASSWORD = "correct horse battery staple"


def _make_user(
    deployment,
    email="analyst@northwind.test",
    *,
    admin=False,
    active=True,
    password=GOOD_PASSWORD,
):
    """A user straight into the database - the operator's path, not a route."""
    from app.core.accounts import create_user

    with deployment.session_factory() as session:
        user = create_user(
            session,
            email=email,
            display_name="Ana Lyst",
            password=password,
            is_admin=admin,
        )
        if not active:
            user.is_active = False
        session.commit()
        return str(user.user_id)


def _login(deployment, email="analyst@northwind.test", password=GOOD_PASSWORD):
    return deployment.client.post(
        f"{PREFIX}/auth/login", json={"email": email, "password": password}
    )


# --- signing in ---------------------------------------------------------------


def test_a_known_user_with_the_right_password_gets_a_session(empty_api):
    _make_user(empty_api)
    response = _login(empty_api)
    assert response.status_code == 200
    assert response.json()["email"] == "analyst@northwind.test"


def test_the_session_cookie_is_not_readable_by_scripts(empty_api):
    """An httpOnly cookie rather than a token the page holds.

    A token in `localStorage` is a token any injected script can read and post
    somewhere. The cookie cannot be read by script at all, which removes the
    entire class rather than mitigating it.
    """
    _make_user(empty_api)
    cookie = _login(empty_api).headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_the_session_token_is_never_stored_as_itself(empty_api):
    """A database read must not hand someone a set of live sessions."""
    from app.db.models import Session

    _make_user(empty_api)
    response = _login(empty_api)
    token = response.cookies["dbb_session"]

    with empty_api.session_factory() as session:
        stored = [row.token_digest for row in session.query(Session).all()]
    assert stored
    assert token not in stored


def test_a_wrong_password_and_an_unknown_user_are_told_the_same_thing(empty_api):
    """Otherwise the login form is a list of who works here.

    Different wording, different status, or a visibly different response time
    all answer "does this address have an account", which is the first half of
    an attack and a privacy leak on its own.
    """
    _make_user(empty_api)
    wrong = _login(empty_api, password="not the password at all")
    unknown = _login(empty_api, email="nobody@northwind.test")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["message"] == unknown.json()["message"]


def test_a_deactivated_user_cannot_sign_in(empty_api):
    _make_user(empty_api, active=False)
    assert _login(empty_api).status_code == 401


def test_signing_in_is_case_insensitive_about_the_address(empty_api):
    """People type their own address with whatever capitalisation they like,
    and an account they cannot get into is a support call."""
    _make_user(empty_api, email="Ana.Lyst@Northwind.test")
    assert _login(empty_api, email="ana.lyst@northwind.test").status_code == 200


# --- staying signed in ---------------------------------------------------------


def test_me_reports_the_signed_in_user(empty_api):
    _make_user(empty_api)
    _login(empty_api)
    response = empty_api.client.get(f"{PREFIX}/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "analyst@northwind.test"


def test_me_without_a_session_is_a_refusal_and_not_an_empty_user(empty_api):
    """`200` with a null user is the shape that makes a client forget to check."""
    assert empty_api.client.get(f"{PREFIX}/auth/me").status_code == 401


def test_signing_out_ends_the_session_immediately(empty_api):
    _make_user(empty_api)
    _login(empty_api)
    assert empty_api.client.post(f"{PREFIX}/auth/logout").status_code == 204
    assert empty_api.client.get(f"{PREFIX}/auth/me").status_code == 401


def test_an_expired_session_is_refused_even_though_the_row_is_there(empty_api):
    from app.db.models import Session

    _make_user(empty_api)
    _login(empty_api)
    with empty_api.session_factory() as session:
        row = session.query(Session).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()
    assert empty_api.client.get(f"{PREFIX}/auth/me").status_code == 401


def test_an_idle_session_is_refused_before_its_absolute_expiry(empty_api):
    """The laptop nobody came back to. Absolute expiry alone leaves a browser
    on a shared machine signed in for the whole window."""
    from app.core.accounts import IDLE_TIMEOUT
    from app.db.models import Session

    _make_user(empty_api)
    _login(empty_api)
    with empty_api.session_factory() as session:
        row = session.query(Session).one()
        row.last_seen_at = datetime.now(timezone.utc) - IDLE_TIMEOUT - timedelta(minutes=1)
        session.commit()
    assert empty_api.client.get(f"{PREFIX}/auth/me").status_code == 401


def test_a_session_that_belongs_to_a_deactivated_user_stops_working(empty_api):
    """Deactivating someone has to end the session they already have, or a
    leaver keeps working until their cookie happens to expire."""
    from app.db.models import User

    _make_user(empty_api)
    _login(empty_api)
    with empty_api.session_factory() as session:
        session.query(User).one().is_active = False
        session.commit()
    assert empty_api.client.get(f"{PREFIX}/auth/me").status_code == 401


def test_a_revoked_session_is_dead_even_if_the_token_is_still_held(empty_api):
    """Signing out also clears the cookie, so the obvious test passes whether or
    not revocation works - found by removing the revocation check and watching
    nothing fail. Someone who kept the token is the case that matters.
    """
    _make_user(empty_api)
    token = _login(empty_api).cookies["dbb_session"]
    empty_api.client.post(f"{PREFIX}/auth/logout")

    empty_api.client.cookies.set("dbb_session", token)
    assert empty_api.client.get(f"{PREFIX}/auth/me").status_code == 401


def test_deactivating_someone_ends_the_session_they_already_have(empty_api):
    """Through `deactivate`, not by setting the flag in the database.

    The flag alone is checked on every request, so a test that sets it directly
    passes without `deactivate` revoking anything - which is how a leaver keeps
    working until their cookie happens to expire.
    """
    from app.core.accounts import deactivate, find_by_email
    from app.db.models import Session

    _make_user(empty_api, email="admin@northwind.test", admin=True)
    _make_user(empty_api, email="leaver@northwind.test")
    _login(empty_api, email="leaver@northwind.test")

    with empty_api.session_factory() as session:
        deactivate(
            session,
            find_by_email(session, "leaver@northwind.test"),
            acting_as=find_by_email(session, "admin@northwind.test"),
        )
        session.commit()
        revoked = [row.revoked_at for row in session.query(Session).all()]

    assert all(moment is not None for moment in revoked), revoked
    assert empty_api.client.get(f"{PREFIX}/auth/me").status_code == 401


def test_an_unknown_address_still_does_the_password_work(empty_api, monkeypatch):
    """Otherwise the response time answers "does this address have an account".

    A short-circuit on an unknown address is the natural way to write this and
    it reads as an optimisation. Found by writing that short-circuit and
    watching every assertion still pass - message equality cannot see timing.
    """
    from app.core import accounts

    calls = []
    real = accounts.verify_password
    monkeypatch.setattr(
        accounts, "verify_password", lambda *a, **k: calls.append(1) or real(*a, **k)
    )
    _make_user(empty_api)
    _login(empty_api, email="nobody-at-all@northwind.test")
    assert calls, "an unknown address returned without verifying anything"


def test_a_forged_token_is_refused(empty_api):
    _make_user(empty_api)
    _login(empty_api)
    empty_api.client.cookies.set("dbb_session", "a" * 43)
    assert empty_api.client.get(f"{PREFIX}/auth/me").status_code == 401


# --- adding people --------------------------------------------------------------


def test_only_an_admin_may_add_a_user(empty_api):
    _make_user(empty_api, admin=False)
    _login(empty_api)
    response = empty_api.client.post(
        f"{PREFIX}/users",
        json={"email": "new@northwind.test", "display_name": "New", "password": GOOD_PASSWORD},
    )
    assert response.status_code == 403


def test_an_admin_may_add_a_user(empty_api):
    _make_user(empty_api, email="admin@northwind.test", admin=True)
    _login(empty_api, email="admin@northwind.test")
    response = empty_api.client.post(
        f"{PREFIX}/users",
        json={"email": "new@northwind.test", "display_name": "New", "password": GOOD_PASSWORD},
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new@northwind.test"


def test_a_user_response_never_carries_a_password_or_its_hash(empty_api):
    _make_user(empty_api, email="admin@northwind.test", admin=True)
    _login(empty_api, email="admin@northwind.test")
    body = empty_api.client.post(
        f"{PREFIX}/users",
        json={"email": "new@northwind.test", "display_name": "New", "password": GOOD_PASSWORD},
    ).text
    assert GOOD_PASSWORD not in body
    assert "scrypt" not in body
    assert "password" not in body.lower()


def test_a_weak_password_is_refused_with_the_rule_in_the_message(empty_api):
    _make_user(empty_api, email="admin@northwind.test", admin=True)
    _login(empty_api, email="admin@northwind.test")
    response = empty_api.client.post(
        f"{PREFIX}/users",
        json={"email": "new@northwind.test", "display_name": "New", "password": "short"},
    )
    assert response.status_code == 422
    assert "12" in response.json()["message"]


def test_the_same_address_cannot_be_registered_twice(empty_api):
    _make_user(empty_api, email="admin@northwind.test", admin=True)
    _login(empty_api, email="admin@northwind.test")
    for _ in range(2):
        response = empty_api.client.post(
            f"{PREFIX}/users",
            json={"email": "TWICE@northwind.test", "display_name": "T", "password": GOOD_PASSWORD},
        )
    assert response.status_code == 409


# --- seats ------------------------------------------------------------------------


def test_adding_a_user_beyond_the_licensed_seats_is_refused(empty_api, monkeypatch):
    """`License.seats` was carried and never used, which makes it decoration."""
    _seat_limit(monkeypatch, 2)
    _make_user(empty_api, email="admin@northwind.test", admin=True)
    _login(empty_api, email="admin@northwind.test")

    first = empty_api.client.post(
        f"{PREFIX}/users",
        json={"email": "b@northwind.test", "display_name": "B", "password": GOOD_PASSWORD},
    )
    second = empty_api.client.post(
        f"{PREFIX}/users",
        json={"email": "c@northwind.test", "display_name": "C", "password": GOOD_PASSWORD},
    )
    assert first.status_code == 201
    assert second.status_code == 402
    assert "2" in second.json()["message"]


def test_deactivating_a_leaver_frees_their_seat_at_once(empty_api, monkeypatch):
    """The count is of *active* users. Charging a customer for people who have
    left punishes them for tidying up."""
    _seat_limit(monkeypatch, 2)
    admin = _make_user(empty_api, email="admin@northwind.test", admin=True)
    _login(empty_api, email="admin@northwind.test")
    empty_api.client.post(
        f"{PREFIX}/users",
        json={"email": "b@northwind.test", "display_name": "B", "password": GOOD_PASSWORD},
    )
    blocked = empty_api.client.post(
        f"{PREFIX}/users",
        json={"email": "c@northwind.test", "display_name": "C", "password": GOOD_PASSWORD},
    )
    assert blocked.status_code == 402

    listed = empty_api.client.get(f"{PREFIX}/users").json()
    leaver = next(u for u in listed["users"] if u["email"] == "b@northwind.test")
    assert (
        empty_api.client.patch(
            f"{PREFIX}/users/{leaver['user_id']}", json={"is_active": False}
        ).status_code
        == 200
    )

    again = empty_api.client.post(
        f"{PREFIX}/users",
        json={"email": "c@northwind.test", "display_name": "C", "password": GOOD_PASSWORD},
    )
    assert again.status_code == 201, again.text


def test_an_admin_cannot_deactivate_themselves(empty_api):
    """Even when another administrator would remain.

    A second admin exists on purpose. Without one, the "last administrator"
    rule refuses this anyway and the self-deactivation rule is never exercised -
    found by removing it and watching the test still pass.
    """
    admin = _make_user(empty_api, email="admin@northwind.test", admin=True)
    _make_user(empty_api, email="other@northwind.test", admin=True)
    _login(empty_api, email="admin@northwind.test")
    response = empty_api.client.patch(f"{PREFIX}/users/{admin}", json={"is_active": False})
    assert response.status_code == 409
    assert "your own account" in response.json()["message"].lower()



def _seat_limit(monkeypatch, seats: int) -> None:
    """Put a licence with `seats` in front of the deployment."""
    from datetime import date

    from app.core import licensing
    from engines.licensing import generate_keypair, issue, verify

    private, public = generate_keypair()
    token = issue(
        private_key=private,
        customer="Northwind Analytics",
        issued=date.today() - timedelta(days=1),
        expires=date.today() + timedelta(days=365),
        features=("convert",),
        seats=seats,
    )
    monkeypatch.setattr(licensing, "VENDOR_PUBLIC_KEY", public)
    monkeypatch.setenv("LICENSE_KEY", token)
    licensing.status.cache_clear()


# --- the bootstrap ------------------------------------------------------------------


def test_there_is_no_route_that_creates_the_first_admin(empty_api):
    """An endpoint that makes an admin when the table is empty makes an admin
    on any deployment whose database has not finished migrating.

    The cookie is cleared first: the shared fixture signs in as an
    administrator, so without this the test would be asserting that an admin
    can add a user - which is a different and already-tested thing.
    """
    empty_api.client.cookies.clear()
    response = empty_api.client.post(
        f"{PREFIX}/users",
        json={"email": "first@northwind.test", "display_name": "F", "password": GOOD_PASSWORD},
    )
    assert response.status_code == 401


def test_the_operator_can_create_the_first_admin_from_the_environment(empty_api, monkeypatch):
    """The same shape as installing a licence: set it where the process reads
    it, restart, and the deployment is usable."""
    from app.core.accounts import bootstrap_admin
    from app.db.models import User

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "root@northwind.test")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", GOOD_PASSWORD)
    with empty_api.session_factory() as session:
        bootstrap_admin(session)
        session.commit()

    assert _login(empty_api, email="root@northwind.test").status_code == 200
    with empty_api.session_factory() as session:
        assert session.query(User).one().is_admin is True


def test_the_bootstrap_does_nothing_once_anyone_exists(empty_api, monkeypatch):
    """Otherwise a variable left in a compose file re-creates an administrator
    after someone deliberately removed one."""
    from app.core.accounts import bootstrap_admin
    from app.db.models import User

    _make_user(empty_api, email="someone@northwind.test")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "root@northwind.test")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", GOOD_PASSWORD)
    with empty_api.session_factory() as session:
        bootstrap_admin(session)
        session.commit()
        assert session.query(User).count() == 1


def test_the_bootstrap_refuses_a_password_that_would_be_refused_anywhere_else(
    empty_api, monkeypatch
):
    """A convenience path that skips the rule is where the weak password lives."""
    from app.core.accounts import bootstrap_admin
    from engines.identity import PasswordTooWeak

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "root@northwind.test")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "admin")
    with empty_api.session_factory() as session:
        with pytest.raises(PasswordTooWeak):
            bootstrap_admin(session)


# --- the gate is real -----------------------------------------------------------------


def test_every_route_that_touches_a_workbook_requires_a_session():
    """Authentication that protects nothing is decoration.

    Enumerated from the application's own routing table rather than from a list
    written here, so a router added tomorrow is covered the day it is added -
    the failure mode this guards against is a new endpoint that is public
    because nobody remembered, and a hand-written list would be the same
    forgetting in a different file.
    """
    from fastapi.routing import APIRoute

    from app.api.accounts import current_user
    from app.main import app

    #: The three that must stay reachable before anyone has signed in, each for
    #: a stated reason. Anything else public is a finding.
    public = {
        "/api/v1/health",  # a load balancer and a starting web app need it
        "/api/v1/license",  # the sign-in page has to be able to say the licence lapsed
        "/api/v1/auth/login",  # signing in cannot require being signed in
        "/api/v1/auth/logout",  # signing out of an already-dead session must not error
    }

    unguarded = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path in public:
            continue
        names = {
            getattr(dependency.call, "__name__", "")
            for dependency in route.dependant.dependencies
        }
        # `current_admin` depends on `current_user`, so either satisfies this.
        if not {"current_user", "current_admin"} & names:
            unguarded.append(f"{sorted(route.methods)} {route.path}")

    assert unguarded == [], (
        f"{unguarded} can be reached without signing in. Add it to the "
        "signed-in routers, or to `public` above with the reason it belongs "
        "there."
    )


def test_a_project_route_is_refused_without_a_session(empty_api):
    """The end-to-end version of the check above, through real HTTP."""
    empty_api.client.cookies.clear()
    response = empty_api.client.get(f"{PREFIX}/projects")
    assert response.status_code == 401
    assert response.json()["category"] == "AUTH_ERROR"
