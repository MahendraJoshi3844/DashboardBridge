"""Signing in, and managing who may (`P7.1`).

Thin, like every router here: validate, authorise, delegate. The decisions -
what a seat is, how long a session lives, why a failed login says only one thing
- are in `app/core/accounts.py`, next to the database they need.

## The session is a cookie, and the cookie is httpOnly

Rather than a token the page holds. A token in `localStorage` is a token any
injected script can read and post somewhere; a cookie marked `httpOnly` cannot
be read by script at all, which removes the class instead of mitigating it.
`SameSite=Lax` is the CSRF half: a cross-site form post does not carry it, and
the app's own navigations do.

`Secure` is set whenever the deployment is not plainly running on http, because
a cookie marked `Secure` on a plain-http install would simply never be sent and
the customer would have a login that silently does nothing.

## There is no route that creates the first administrator

Installing a licence is putting a file on the machine and restarting; so is
making the first account. An endpoint that creates an admin when the table is
empty creates one on any deployment whose database has not finished migrating.
`bootstrap_admin` reads it from the environment at start-up instead.
"""

from __future__ import annotations

from uuid import UUID

from dashboardbridge_contracts import (
    CreateUserRequest,
    LoginRequest,
    UpdateUserRequest,
    UserAccount,
    UserList,
)
from dashboardbridge_contracts.enums import ErrorCategory
from fastapi import APIRouter, Depends, Request, Response, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core import accounts
from app.core.db import get_session
from app.core.errors import ApiException
from app.db.models import User
from engines.identity import PasswordTooWeak

router = APIRouter(tags=["accounts"])


def _to_contract(user: User) -> UserAccount:
    return UserAccount(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        products=sorted(user.products),
    )


def _unauthenticated() -> ApiException:
    return ApiException(
        ErrorCategory.AUTH_ERROR,
        "Sign in to continue.",
        status_code=http_status.HTTP_401_UNAUTHORIZED,
    )


def current_user(
    request: Request, session: DbSession = Depends(get_session)
) -> User:
    """The signed-in user, or a 401.

    A dependency rather than middleware so that a route which does not want it
    simply does not ask - and, more importantly, so a route that *should* have
    it and does not is visible in its own signature rather than in a list of
    path prefixes somewhere else.
    """
    user = accounts.user_for_token(session, request.cookies.get(accounts.COOKIE_NAME))
    if user is None:
        raise _unauthenticated()
    return user


def current_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise ApiException(
            ErrorCategory.AUTH_ERROR,
            "Only an administrator can manage accounts on this deployment.",
            status_code=http_status.HTTP_403_FORBIDDEN,
        )
    return user


@router.post("/auth/login", response_model=UserAccount)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: DbSession = Depends(get_session),
) -> UserAccount:
    result = accounts.sign_in(session, email=body.email, password=body.password)
    if result is None:
        # One sentence for every kind of failure - no such address, wrong
        # password, deactivated account. A form that can tell them apart is a
        # list of who works here.
        raise ApiException(
            ErrorCategory.AUTH_ERROR,
            "That email address and password do not match an active account.",
            status_code=http_status.HTTP_401_UNAUTHORIZED,
        )
    user, token = result
    response.set_cookie(
        accounts.COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=int(accounts.SESSION_LIFETIME.total_seconds()),
        path="/",
    )
    # Commit before answering. The request's session scope only closes after
    # the response is sent (FastAPI runs yield-dependency teardown late), so a
    # client that follows up at once - /auth/me right after signing in, an
    # upload right after creating the project - could otherwise not see this.
    session.commit()
    return _to_contract(user)


@router.post("/auth/logout", status_code=http_status.HTTP_204_NO_CONTENT)
def logout(
    request: Request, response: Response, session: DbSession = Depends(get_session)
) -> None:
    accounts.sign_out(session, request.cookies.get(accounts.COOKIE_NAME))
    session.commit()  # the session is revoked before the client is told it is
    response.delete_cookie(accounts.COOKIE_NAME, path="/")


@router.get("/auth/me", response_model=UserAccount)
def me(user: User = Depends(current_user)) -> UserAccount:
    """Who am I? A 401 when nobody, never a 200 with an empty user - that shape
    is what makes a client forget to check."""
    return _to_contract(user)


@router.get("/users", response_model=UserList)
def list_users(
    _: User = Depends(current_user), session: DbSession = Depends(get_session)
) -> UserList:
    """Readable by everyone here. These are colleagues on a shared deployment,
    and hiding who else uses it protects nothing while making it harder to know
    whose conversion a project was."""
    from app.core.licensing import status

    licence = status().license
    return UserList(
        users=[
            _to_contract(row)
            for row in session.scalars(select(User).order_by(User.created_at))
        ],
        seats_total=licence.seats if licence and licence.seats else None,
        seats_used=accounts.active_user_count(session),
    )


@router.post(
    "/users", response_model=UserAccount, status_code=http_status.HTTP_201_CREATED
)
def add_user(
    body: CreateUserRequest,
    _: User = Depends(current_admin),
    session: DbSession = Depends(get_session),
) -> UserAccount:
    try:
        user = accounts.create_user(
            session,
            email=body.email,
            display_name=body.display_name,
            password=body.password,
            products=body.products,
        )
    except PasswordTooWeak as weak:
        # 422 with the rule in it. "Too weak" without the rule sends someone
        # guessing at what would be accepted.
        raise ApiException(
            ErrorCategory.AUTH_ERROR,
            str(weak),
            status_code=422,
        ) from weak
    except accounts.AccountError as refusal:
        raise ApiException(
            ErrorCategory.AUTH_ERROR,
            refusal.message,
            status_code=refusal.status_code,
        ) from refusal
    session.commit()  # visible to the next request at once
    return _to_contract(user)


@router.patch("/users/{user_id}", response_model=UserAccount)
def update_user(
    user_id: UUID,
    body: UpdateUserRequest,
    acting_as: User = Depends(current_admin),
    session: DbSession = Depends(get_session),
) -> UserAccount:
    user = session.get(User, user_id)
    if user is None:
        raise ApiException(
            ErrorCategory.NOT_FOUND,
            "There is no account with that id on this deployment.",
            status_code=http_status.HTTP_404_NOT_FOUND,
        )

    try:
        if body.is_active is False:
            accounts.deactivate(session, user, acting_as=acting_as)
        elif body.is_active is True and not user.is_active:
            left = accounts.seats_available(session)
            if left is not None and left <= 0:
                raise accounts.NoSeatsLeft(
                    "Reactivating this account would exceed the seats this "
                    "licence covers. Deactivate someone else, or ask for more."
                )
            user.is_active = True
        if body.is_admin is not None:
            user.is_admin = body.is_admin
        if body.products is not None:
            accounts.set_products(user, body.products)
    except accounts.AccountError as refusal:
        raise ApiException(
            ErrorCategory.AUTH_ERROR,
            refusal.message,
            status_code=refusal.status_code,
        ) from refusal

    session.commit()  # visible to the next request at once
    return _to_contract(user)
