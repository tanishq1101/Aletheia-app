"""Clerk session verification and per-user scoping.

Every request used to be the same seeded development user, so "whose project is
this" had one answer and authorisation was not a question anyone asked. This
module makes the caller's identity a fact the API establishes for itself
instead of a value it assumes.

Verification is local. Clerk signs session tokens with RS256 and publishes the
public half at a JWKS endpoint, so a token is checked against a cached key
rather than by calling Clerk on every request — one network round trip per key
rotation, not per request. The secret key is never needed for this and is not
read here.

Failing closed is the point: with no issuer configured the API refuses to start
unless someone has *explicitly* said unauthenticated access is intended. A
deployment that forgets to set CLERK_ISSUER gets a startup error, not an open
database.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt import PyJWKClient

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_connection

log = get_logger(__name__)

# Clock skew allowance. Clerk's own SDKs use 5s; tokens are short-lived
# (~60s), so a wider window would meaningfully extend a stolen token's life.
LEEWAY_SECONDS = 5


class AuthError(HTTPException):
    """401 with a reason the caller can act on.

    The reason is deliberately about *the token*, never about whether an
    account exists — a message that distinguishes "no such user" from "wrong
    password" is a user-enumeration oracle.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


@dataclass(frozen=True)
class AuthenticatedUser:
    """A verified caller, resolved to this database's own user row."""

    id: UUID
    clerk_user_id: str | None
    email: str | None
    username: str | None
    #: True when auth is switched off and this is the seeded development user.
    is_development: bool = False


class _JWKSCache:
    """Clerk's signing keys, fetched once and reused.

    PyJWKClient caches internally but is not documented as thread-safe to
    construct concurrently, and building it per request would fetch JWKS per
    request. One instance, guarded, built lazily so importing this module never
    touches the network — which is what keeps the test suite offline.
    """

    def __init__(self) -> None:
        self._client: PyJWKClient | None = None
        self._url: str | None = None
        self._lock = threading.Lock()

    def client(self, url: str) -> PyJWKClient:
        with self._lock:
            if self._client is None or self._url != url:
                self._client = PyJWKClient(url, cache_keys=True, lifespan=3600)
                self._url = url
            return self._client

    def reset(self) -> None:
        with self._lock:
            self._client = None
            self._url = None


_jwks = _JWKSCache()


def reset_jwks_cache() -> None:
    """Drop cached signing keys. For tests and key rotation."""
    _jwks.reset()


def _issuer() -> str:
    return get_settings().clerk_issuer.rstrip("/")


def _jwks_url() -> str:
    settings = get_settings()
    if settings.clerk_jwks_url:
        return settings.clerk_jwks_url
    return f"{_issuer()}/.well-known/jwks.json"


def verify_token(token: str) -> dict[str, Any]:
    """Verify a Clerk session JWT and return its claims.

    Raises AuthError for anything that makes the token untrustworthy. The
    distinction that matters here is between "this token is not valid" (401,
    the caller can re-authenticate) and "we cannot check right now" (503, the
    caller should retry) — collapsing the second into the first would tell a
    legitimate user to sign in again during a Clerk outage, and collapsing the
    first into the second would hide a forged token as an infrastructure blip.
    """
    settings = get_settings()
    try:
        signing_key = _jwks.client(_jwks_url()).get_signing_key_from_jwt(token)
    except jwt.exceptions.PyJWKClientConnectionError as exc:
        log.error("Could not fetch Clerk JWKS: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Cannot verify the session right now: the identity provider's "
                "signing keys are unreachable. This is not a problem with your "
                "account."
            ),
        ) from exc
    except jwt.exceptions.PyJWKClientError as exc:
        # An unknown `kid` is the normal shape of a forged or stale token.
        raise AuthError(f"Session token is not signed by a known key: {exc}") from exc
    except jwt.InvalidTokenError as exc:
        # Finding the signing key means reading the token's header, so a value
        # that is not a JWT at all fails *here*, before the decode below ever
        # runs. DecodeError is a sibling of PyJWKClientError rather than a
        # subclass, so without this clause `Authorization: Bearer nonsense`
        # left an unhandled exception and answered 500 — an unauthenticated
        # caller could fill the error log at will, and a 500 on the auth path
        # reads like a broken server rather than a rejected credential.
        raise AuthError(f"Session token is not valid: {exc}") from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=_issuer(),
            leeway=LEEWAY_SECONDS,
            options={
                "require": ["exp", "iat", "sub", "iss"],
                "verify_aud": bool(settings.clerk_audience),
            },
            audience=settings.clerk_audience or None,
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Session has expired. Sign in again.") from exc
    except jwt.InvalidIssuerError as exc:
        raise AuthError("Session token was issued by a different application.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"Session token is not valid: {exc}") from exc

    # `nbf` is optional in Clerk's tokens but must be honoured when present;
    # PyJWT already does that. What it does not do is reject a token whose
    # `azp` (authorised party) is some other origin, which is the check that
    # stops a token minted for a different site being replayed here.
    allowed = settings.clerk_authorized_parties
    azp = claims.get("azp")
    if allowed and azp and azp not in allowed:
        raise AuthError("Session token was issued for a different origin.")

    if not claims.get("sub"):
        raise AuthError("Session token carries no subject.")
    return claims


def _resolve_user(claims: dict[str, Any]) -> AuthenticatedUser:
    """Map a verified Clerk subject to this database's user row.

    Provisioning happens here, on first request, rather than through a webhook:
    a webhook that has not arrived yet would leave a signed-in user staring at
    an error, and this path is idempotent under concurrency because the insert
    resolves the conflict itself instead of testing for existence first.
    """
    subject = str(claims["sub"])
    email = claims.get("email") or claims.get("primary_email_address")
    username = claims.get("username") or claims.get("name")

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (clerk_user_id, email, username, last_seen_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (clerk_user_id) DO UPDATE
                SET email        = COALESCE(EXCLUDED.email, users.email),
                    username     = COALESCE(EXCLUDED.username, users.username),
                    last_seen_at = now()
            RETURNING id, clerk_user_id, email, username
            """,
            (subject, email, username),
        )
        row = cur.fetchone()

    return AuthenticatedUser(
        id=row["id"],
        clerk_user_id=row["clerk_user_id"],
        email=row["email"],
        username=row["username"],
    )


def _development_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=UUID(get_settings().dev_user_id),
        clerk_user_id=None,
        email=None,
        username="development",
        is_development=True,
    )


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def get_current_user(request: Request) -> AuthenticatedUser:
    """FastAPI dependency: the verified caller, or 401.

    When auth is disabled this returns the seeded development user, so every
    route reads identically in both modes and no route has to remember to
    handle a missing user.
    """
    settings = get_settings()
    if not settings.auth_enabled:
        return _development_user()

    token = _bearer_token(request)
    if token is None:
        raise AuthError("This endpoint requires a signed-in session.")
    user = _resolve_user(verify_token(token))
    request.state.user = user
    return user


def get_current_user_id(
    user: AuthenticatedUser = Depends(get_current_user),
) -> str:
    """The caller's local user id, as the string the queries already expect."""
    return str(user.id)


def check_auth_configuration() -> None:
    """Refuse to start in a state that silently serves everyone's data.

    Called from the app lifespan. An API that is *meant* to be open can say so
    with ALLOW_UNAUTHENTICATED=true; one that merely forgot its issuer gets a
    loud failure instead of an open door.
    """
    settings = get_settings()
    if settings.auth_enabled:
        log.info("Authentication enabled — issuer=%s", _issuer())
        return
    if not settings.allow_unauthenticated:
        raise RuntimeError(
            "No authentication is configured. Set CLERK_ISSUER (and "
            "CLERK_PUBLISHABLE_KEY in the frontend) to require sign-in, or set "
            "ALLOW_UNAUTHENTICATED=true to state explicitly that this instance "
            "is meant to be open. Refusing to start with an unauthenticated "
            "API by accident."
        )
    log.warning(
        "AUTHENTICATION IS DISABLED (ALLOW_UNAUTHENTICATED=true). Every request "
        "is treated as the seeded development user %s and anyone who can reach "
        "this API can read and change everything in it. Do not expose this to a "
        "network.",
        settings.dev_user_id,
    )
