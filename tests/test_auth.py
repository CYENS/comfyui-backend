"""Auth endpoint test suite.

Each test is a runnable proof of a specific auth contract. Together they
document the expected behaviour of all five auth endpoints and several
security properties that are not otherwise visible in the code.

Endpoints covered:
  GET  /api/auth/dev
  POST /api/auth/login
  POST /api/auth/refresh
  POST /api/auth/logout
  GET  /api/auth/me
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db
from app.limiter import limiter
from app.models import RefreshToken, RoleName, User
from app.routers import auth
from app.security import hash_token, verify_password
from app.seeding import seed_roles_and_system_user, seed_user_with_roles

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def client_and_session(tmp_path, monkeypatch):
    """Isolated SQLite DB, auth router only, JWT mode enforced."""
    db_path = tmp_path / "test_auth.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(auth.router, prefix="/api")

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "auth_dev_mode", False)

    # The limiter is a module-level singleton; reset its storage so previous
    # tests' login calls don't consume this test's quota.
    limiter._storage.reset()

    with TestClient(app) as client:
        db = TestingSessionLocal()
        try:
            seed_roles_and_system_user(db)
            yield client, db
        finally:
            db.close()
            app.dependency_overrides.clear()
            engine.dispose()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_user(
    db, client, username="alice", password="secret", roles=None
) -> tuple[User, str, str]:
    """Seed a user and log in to obtain a real token pair.

    Returns (user, access_token, refresh_token).
    """
    if roles is None:
        roles = [RoleName.JOB_CREATOR]
    user = seed_user_with_roles(db, username, password, roles)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    body = res.json()
    return user, body["access_token"], body["refresh_token"]


# ---------------------------------------------------------------------------
# GET /api/auth/dev
# ---------------------------------------------------------------------------


def test_dev_status_off(client_and_session):
    client, _db = client_and_session
    res = client.get("/api/auth/dev")
    assert res.status_code == 200
    body = res.json()
    assert body["auth_dev_mode"] is False
    assert body["default_user_id"] is None
    assert body["default_roles"] is None


def test_dev_status_on(client_and_session, monkeypatch):
    client, _db = client_and_session
    monkeypatch.setattr(settings, "auth_dev_mode", True)
    monkeypatch.setattr(settings, "auth_dev_user_id", "dev-tester")
    monkeypatch.setattr(settings, "auth_dev_user_roles", "admin,viewer")

    res = client.get("/api/auth/dev")
    assert res.status_code == 200
    body = res.json()
    assert body["auth_dev_mode"] is True
    assert body["default_user_id"] == "dev-tester"
    assert isinstance(body["default_roles"], list)
    assert "admin" in body["default_roles"]


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------


def test_login_valid_credentials(client_and_session):
    client, db = client_and_session
    seed_user_with_roles(db, "alice", "secret", [RoleName.JOB_CREATOR])

    res = client.post("/api/auth/login", json={"username": "alice", "password": "secret"})

    assert res.status_code == 200
    body = res.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["user"]["username"] == "alice"
    assert isinstance(body["user"]["roles"], list)


def test_login_wrong_password(client_and_session):
    client, db = client_and_session
    seed_user_with_roles(db, "alice", "secret", [RoleName.JOB_CREATOR])

    res = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})

    assert res.status_code == 401


def test_login_unknown_username(client_and_session):
    client, _db = client_and_session

    res = client.post("/api/auth/login", json={"username": "nobody", "password": "secret"})

    assert res.status_code == 401


def test_login_response_roles_match_db(client_and_session):
    client, db = client_and_session
    seed_user_with_roles(db, "alice", "secret", [RoleName.JOB_CREATOR, RoleName.VIEWER])

    res = client.post("/api/auth/login", json={"username": "alice", "password": "secret"})

    assert res.status_code == 200
    returned_roles = set(res.json()["user"]["roles"])
    assert returned_roles == {"job_creator", "viewer"}


# ---------------------------------------------------------------------------
# POST /api/auth/refresh
# ---------------------------------------------------------------------------


def test_refresh_issues_new_token_pair(client_and_session):
    client, db = client_and_session
    _user, _at, refresh_token = _make_user(db, client)

    res = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})

    assert res.status_code == 200
    body = res.json()
    assert "access_token" in body
    assert "refresh_token" in body


def test_refresh_revokes_old_token(client_and_session):
    client, db = client_and_session
    _user, _at, refresh_token = _make_user(db, client)

    # First refresh is fine
    res1 = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert res1.status_code == 200

    # Re-using the old token is rejected
    res2 = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert res2.status_code == 401


def test_refresh_unknown_token(client_and_session):
    client, _db = client_and_session

    res = client.post("/api/auth/refresh", json={"refresh_token": "totally-made-up-token"})

    assert res.status_code == 401


def test_refresh_already_revoked_token(client_and_session):
    client, db = client_and_session
    _user, _at, refresh_token = _make_user(db, client)

    # Revoke directly in DB
    record = (
        db.query(RefreshToken).filter(RefreshToken.token_hash == hash_token(refresh_token)).one()
    )
    record.revoked_at = datetime.now(UTC)
    db.add(record)
    db.commit()

    res = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert res.status_code == 401


def test_refresh_expired_token(client_and_session):
    client, db = client_and_session
    user, _at, _rt = _make_user(db, client)

    # Insert a pre-expired refresh token directly
    raw = "expired-token-value-" + uuid.uuid4().hex
    record = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=hash_token(raw),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    db.add(record)
    db.commit()

    res = client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------


def test_logout_revokes_token(client_and_session):
    client, db = client_and_session
    _user, _at, refresh_token = _make_user(db, client)

    logout_res = client.post("/api/auth/logout", json={"refresh_token": refresh_token})
    assert logout_res.status_code == 200

    refresh_res = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_res.status_code == 401


def test_logout_idempotent_unknown_token(client_and_session):
    client, _db = client_and_session

    res = client.post("/api/auth/logout", json={"refresh_token": "unknown-token"})

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_logout_idempotent_already_revoked(client_and_session):
    client, db = client_and_session
    _user, _at, refresh_token = _make_user(db, client)

    res1 = client.post("/api/auth/logout", json={"refresh_token": refresh_token})
    res2 = client.post("/api/auth/logout", json={"refresh_token": refresh_token})

    assert res1.status_code == 200
    assert res2.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------


def test_me_returns_current_user(client_and_session):
    client, db = client_and_session
    user, access_token, _rt = _make_user(db, client, username="alice", roles=[RoleName.VIEWER])

    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})

    assert res.status_code == 200
    body = res.json()
    assert body["id"] == user.id
    assert body["username"] == "alice"
    assert "viewer" in body["roles"]


def test_me_requires_auth(client_and_session):
    client, _db = client_and_session

    res = client.get("/api/auth/me")

    assert res.status_code == 401


def test_me_rejects_expired_jwt(client_and_session):
    client, db = client_and_session
    user = seed_user_with_roles(db, "alice", "secret", [RoleName.VIEWER])

    # Craft a JWT that is already expired
    now = datetime.now(UTC)
    payload = {
        "sub": user.id,
        "roles": ["viewer"],
        "iss": settings.auth_issuer,
        "iat": int((now - timedelta(hours=2)).timestamp()),
        "exp": int((now - timedelta(hours=1)).timestamp()),
        "typ": "access",
    }
    expired_token = pyjwt.encode(
        payload, settings.auth_jwt_secret, algorithm=settings.auth_jwt_algorithm
    )

    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"})

    assert res.status_code == 401


def test_me_rejects_wrong_token_type(client_and_session):
    client, db = client_and_session
    user = seed_user_with_roles(db, "alice", "secret", [RoleName.VIEWER])

    now = datetime.now(UTC)
    payload = {
        "sub": user.id,
        "roles": ["viewer"],
        "iss": settings.auth_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "typ": "refresh",  # wrong type
    }
    refresh_shaped_token = pyjwt.encode(
        payload, settings.auth_jwt_secret, algorithm=settings.auth_jwt_algorithm
    )

    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {refresh_shaped_token}"})

    assert res.status_code == 401


def test_me_dev_mode_with_headers(client_and_session, monkeypatch):
    client, db = client_and_session
    # Create the user so the DB lookup in /me succeeds (dev mode bypasses JWT but still queries DB)
    seed_user_with_roles(db, "dev-alice", "secret", [RoleName.ADMIN])
    monkeypatch.setattr(settings, "auth_dev_mode", True)
    monkeypatch.setattr(settings, "auth_dev_user_id", "dev-alice")

    res = client.get(
        "/api/auth/me",
        headers={"X-User-Id": "dev-alice", "X-User-Roles": "admin"},
    )

    assert res.status_code == 200
    assert res.json()["username"] == "dev-alice"


def test_me_dev_mode_default_identity(client_and_session, monkeypatch):
    client, _db = client_and_session
    monkeypatch.setattr(settings, "auth_dev_mode", True)
    monkeypatch.setattr(settings, "auth_dev_user_id", "default-dev-user")
    monkeypatch.setattr(settings, "auth_dev_user_roles", "admin")

    # No Authorization header, no X-User-* headers — falls back to defaults
    res = client.get("/api/auth/me")

    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "default-dev-user"
    assert "admin" in body["roles"]


# ---------------------------------------------------------------------------
# Security properties (unit-style, query the DB directly)
# ---------------------------------------------------------------------------


def test_refresh_token_stored_as_hash(client_and_session):
    """The plaintext refresh token must never appear in the DB."""
    client, db = client_and_session
    _user, _at, refresh_token = _make_user(db, client)

    record = (
        db.query(RefreshToken).filter(RefreshToken.token_hash == hash_token(refresh_token)).one()
    )
    assert record.token_hash != refresh_token
    assert record.token_hash == hash_token(refresh_token)


def test_password_not_stored_plaintext(client_and_session):
    """Passwords must be stored as a salted hash, never in cleartext."""
    client, db = client_and_session
    plaintext = "my-super-secret"
    user = seed_user_with_roles(db, "alice", plaintext, [RoleName.VIEWER])

    db.refresh(user)
    assert user.password_hash != plaintext
    assert verify_password(plaintext, user.password_hash) is True
