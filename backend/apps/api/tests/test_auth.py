"""Authentication, ownership and rate limiting.

These are the three things that were missing when the API's own review said
"anyone who can reach the API reads and writes everything". Each is tested for
the failure it is supposed to prevent, not just for the happy path — a guard
that only has a passing test proves nothing about what it refuses.

Tokens are minted here against a throwaway RSA key and the JWKS lookup is
stubbed, so nothing contacts Clerk and the suite stays offline.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest
from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.core.config import get_settings
from app.core.rate_limit import SlidingWindow
from app.db.session import get_connection
from main import app

ISSUER = "https://example.clerk.accounts.dev"


@pytest.fixture(scope="module")
def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


def mint(keypair, **overrides) -> str:
    private, _ = keypair
    now = datetime.now(UTC)
    claims = {
        "sub": "user_test_subject",
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=1),
    }
    claims.update(overrides)
    return jwt.encode(claims, private, algorithm="RS256")


@pytest.fixture
def authenticated(monkeypatch, keypair):
    """Turn auth on for one test, with the JWKS lookup served locally."""
    _, public = keypair
    settings = get_settings()
    monkeypatch.setattr(settings, "clerk_issuer", ISSUER, raising=False)

    class StubKey:
        key = public

    class StubClient:
        def get_signing_key_from_jwt(self, token):
            # The real PyJWKClient reads the token's header to find the `kid`
            # before it can return anything, so a value that is not a JWT
            # fails *here*, not in the later decode. A stub that hands back a
            # key for any string is more forgiving than the thing it stands in
            # for, and it hid a real 500: this one line is the difference
            # between this fixture testing the code and flattering it.
            jwt.get_unverified_header(token)
            return StubKey()

    monkeypatch.setattr(auth_module._jwks, "client", lambda url: StubClient())
    yield
    auth_module.reset_jwks_cache()


# --- Token verification ------------------------------------------------------


def test_a_valid_token_is_accepted(authenticated, keypair):
    claims = auth_module.verify_token(mint(keypair))
    assert claims["sub"] == "user_test_subject"


def test_an_expired_token_is_refused(authenticated, keypair):
    expired = datetime.now(UTC) - timedelta(hours=1)
    with pytest.raises(auth_module.AuthError) as excinfo:
        auth_module.verify_token(mint(keypair, exp=expired, iat=expired))
    assert excinfo.value.status_code == 401
    assert "expired" in excinfo.value.detail.lower()


def test_a_token_from_another_issuer_is_refused(authenticated, keypair):
    with pytest.raises(auth_module.AuthError):
        auth_module.verify_token(mint(keypair, iss="https://attacker.example"))


def test_a_token_signed_by_a_different_key_is_refused(authenticated):
    """The whole point of signature verification: a well-formed lie fails."""
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    forged = jwt.encode(
        {"sub": "user_test_subject", "iss": ISSUER, "iat": now,
         "exp": now + timedelta(minutes=1)},
        other,
        algorithm="RS256",
    )
    with pytest.raises(auth_module.AuthError):
        auth_module.verify_token(forged)


def test_an_unsigned_token_is_refused(authenticated, keypair):
    """`alg: none` is the classic JWT bypass. Only RS256 is accepted."""
    now = datetime.now(UTC)
    unsigned = jwt.encode(
        {"sub": "x", "iss": ISSUER, "iat": now, "exp": now + timedelta(minutes=1)},
        key="",
        algorithm="none",
    )
    with pytest.raises(auth_module.AuthError):
        auth_module.verify_token(unsigned)


def test_a_token_for_another_origin_is_refused(authenticated, keypair, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        settings, "clerk_authorized_parties_csv", "https://app.example", raising=False
    )
    with pytest.raises(auth_module.AuthError) as excinfo:
        auth_module.verify_token(mint(keypair, azp="https://evil.example"))
    assert "different origin" in excinfo.value.detail


# --- The endpoints actually require it ---------------------------------------


def test_endpoints_refuse_an_anonymous_caller_when_auth_is_on(authenticated):
    with TestClient(app) as client:
        response = client.get("/projects")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "value",
    [
        "not-a-jwt",
        "",
        "a.b",
        "...",
        "eyJhbGciOiJSUzI1NiJ9",  # a header and nothing else
    ],
)
def test_endpoints_refuse_a_garbage_token(authenticated, value):
    """A malformed credential is a 401, never a 500.

    Finding the signing key parses the token header, so anything that is not a
    JWT raises before verification begins. That exception is a sibling of the
    JWKS errors rather than a subclass, so it escaped both handlers and
    answered 500 — which let an unauthenticated caller write a traceback into
    the log on demand, and made a rejected credential look like a broken
    server. Only found by running a real JWKS; the stub used to be more
    forgiving than PyJWKClient.
    """
    with TestClient(app) as client:
        response = client.get("/projects", headers={"Authorization": f"Bearer {value}"})
    assert response.status_code == 401, f"{value!r} produced {response.status_code}"
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_malformed_token_raises_auth_error_not_an_unhandled_one(authenticated):
    with pytest.raises(auth_module.AuthError):
        auth_module.verify_token("not-a-jwt")


def test_health_stays_open(authenticated):
    """A liveness probe that needs a session reports the wrong system's health."""
    with TestClient(app) as client:
        assert client.get("/health").status_code in (200, 503)


# --- Ownership ---------------------------------------------------------------


@pytest.fixture
def other_users_project():
    """A project belonging to somebody who is not the caller."""
    stranger = uuid4()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO users (id) VALUES (%s)", (str(stranger),))
        cur.execute(
            "INSERT INTO projects (user_id, name) VALUES (%s, %s) RETURNING id",
            (str(stranger), "Not yours"),
        )
        project_id = cur.fetchone()["id"]
        conn.commit()
    yield str(project_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (str(stranger),))
        conn.commit()


def test_another_users_project_reads_as_missing(client, other_users_project):
    """404 rather than 403: a 403 would confirm the id exists."""
    response = client.get(f"/projects/{other_users_project}")
    assert response.status_code == 404


def test_another_users_project_cannot_be_deleted(client, other_users_project):
    assert client.delete(f"/projects/{other_users_project}").status_code == 404
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE id = %s", (other_users_project,))
        assert cur.fetchone() is not None, "the project was deleted anyway"


def test_another_users_project_cannot_be_searched(client, other_users_project):
    response = client.post(
        f"/projects/{other_users_project}/search", json={"query": "anything"}
    )
    assert response.status_code == 404


def test_another_users_project_cannot_be_uploaded_to(client, other_users_project):
    response = client.post(
        f"/projects/{other_users_project}/papers",
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
    )
    assert response.status_code == 404


def test_your_own_project_still_works(client, project):
    assert client.get(f"/projects/{project['id']}").status_code == 200


def test_a_malformed_id_is_not_a_500(client):
    assert client.get("/projects/not-a-uuid").status_code in (404, 422)


# --- Rate limiting -----------------------------------------------------------


def test_the_window_refuses_the_request_after_the_limit():
    window = SlidingWindow()
    assert all(window.allow("k", 3, 60.0)[0] for _ in range(3))
    allowed, retry_after = window.allow("k", 3, 60.0)
    assert not allowed
    assert 0 < retry_after <= 60


def test_callers_have_separate_budgets():
    window = SlidingWindow()
    for _ in range(3):
        window.allow("a", 3, 60.0)
    assert window.allow("b", 3, 60.0)[0], "one caller exhausted another's budget"


def test_the_window_slides_rather_than_resetting(monkeypatch):
    """A fixed window lets a caller spend two budgets across the boundary."""
    window = SlidingWindow()
    clock = [1000.0]
    monkeypatch.setattr("app.core.rate_limit.time.monotonic", lambda: clock[0])
    for _ in range(2):
        window.allow("k", 2, 60.0)
    assert not window.allow("k", 2, 60.0)[0]
    clock[0] += 61
    assert window.allow("k", 2, 60.0)[0]


def test_the_limiter_returns_429_with_retry_after(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "rate_limit_requests_per_minute", 3, raising=False)
    with TestClient(app) as client:
        statuses = [client.get("/projects").status_code for _ in range(5)]
        limited = client.get("/projects")
    assert 429 in statuses or limited.status_code == 429
    if limited.status_code == 429:
        assert int(limited.headers["Retry-After"]) >= 1
        assert "Rate limit reached" in limited.json()["detail"]


def test_health_is_never_rate_limited(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "rate_limit_requests_per_minute", 1, raising=False)
    with TestClient(app) as client:
        codes = {client.get("/health").status_code for _ in range(5)}
    assert 429 not in codes


# --- The startup guard -------------------------------------------------------


def test_startup_refuses_an_accidentally_open_api(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "clerk_issuer", "", raising=False)
    monkeypatch.setattr(settings, "allow_unauthenticated", False, raising=False)
    with pytest.raises(RuntimeError, match="No authentication is configured"):
        auth_module.check_auth_configuration()


def test_startup_allows_an_explicitly_open_api(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "clerk_issuer", "", raising=False)
    monkeypatch.setattr(settings, "allow_unauthenticated", True, raising=False)
    auth_module.check_auth_configuration()
