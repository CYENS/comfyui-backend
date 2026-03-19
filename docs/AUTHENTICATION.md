# Authentication — Backend

## Overview

The backend uses **JWT access tokens** paired with **rotating refresh tokens**. A development bypass mode (`AUTH_DEV_MODE`) is available for local use without real credentials.

- **Access tokens** — short-lived JWTs (default: 60 min), sent as `Authorization: Bearer <token>`.
- **Refresh tokens** — long-lived opaque tokens (default: 14 days), stored hashed in the DB. Each use rotates the token (old one is revoked, new one issued).
- **Dev mode** — bypass JWT entirely; identity is taken from `X-User-Id` / `X-User-Roles` request headers.

---

## Configuration (`backend/.env`)

| Variable | Default | Description |
|---|---|---|
| `AUTH_JWT_SECRET` | `change-me-in-production` | HMAC-SHA256 signing key — **change this** |
| `AUTH_JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `AUTH_ACCESS_TOKEN_TTL_MINUTES` | `60` | Access token lifetime |
| `AUTH_REFRESH_TOKEN_TTL_DAYS` | `14` | Refresh token lifetime |
| `AUTH_ISSUER` | `comfyui-wrapper-backend` | JWT `iss` claim |
| `AUTH_DEV_MODE` | `false` | Enable dev bypass (set to `true` for local dev) |
| `AUTH_DEV_USER_ID` | `dev-admin` | Default user ID when dev mode is on |
| `AUTH_DEV_USER_ROLES` | `admin` | Default roles (CSV) when dev mode is on |

All values are read by `app/config.py` via pydantic-settings.

---

## Dev mode

When `AUTH_DEV_MODE=true`:

- **No JWT validation occurs.** Any request without an `Authorization` header is accepted.
- Identity comes from `X-User-Id` and `X-User-Roles` headers (comma-separated role names).
- If the headers are absent, the configured defaults (`AUTH_DEV_USER_ID`, `AUTH_DEV_USER_ROLES`) are used instead.
- If no roles resolve, `ADMIN` is assumed.
- `GET /api/auth/dev` returns the current mode status and defaults — the frontend uses this to detect dev mode on startup.

**Never enable dev mode in production.**

---

## User management

Users are stored in the `users` table with PBKDF2-SHA256 hashed passwords (`passlib` with the `pbkdf2_sha256` scheme — no 72-byte limit, unlike bcrypt).

Seed the DB with initial roles and sample users:

```bash
cd backend
uv run python -m app.seed
```

Users can be created via `POST /api/users` (ADMIN only).

---

## API endpoints

All endpoints live under `/api/auth`.

### `POST /api/auth/login`

Authenticate with username + password. Returns an access/refresh token pair.

**Request:**
```json
{ "username": "alice", "password": "secret" }
```

**Response (`200`):**
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in_seconds": 3600,
  "refresh_token": "<opaque>",
  "user": { "id": "...", "username": "alice", "roles": ["job_creator"] }
}
```

Rate-limited to **10 requests/minute**.

---

### `POST /api/auth/refresh`

Exchange a valid refresh token for a new access + refresh token pair. The old refresh token is revoked immediately (rotation).

**Request:**
```json
{ "refresh_token": "<opaque>" }
```

**Response:** same shape as `/login`.

**Errors:**
- `401` — token not found, already revoked, or expired.

---

### `POST /api/auth/logout`

Revoke a refresh token. Idempotent — silently does nothing if the token is already revoked or not found.

**Request:**
```json
{ "refresh_token": "<opaque>" }
```

**Response:** `{ "status": "ok" }`

---

### `GET /api/auth/me`

Return the currently authenticated user. Requires a valid JWT (or dev mode).

**Response:**
```json
{ "id": "...", "username": "alice", "roles": ["job_creator", "viewer"] }
```

---

### `GET /api/auth/dev`

Return the current dev mode status. Always public (no auth required).

**Response (dev mode on):**
```json
{
  "auth_dev_mode": true,
  "default_user_id": "dev-admin",
  "default_roles": ["admin"]
}
```

**Response (dev mode off):**
```json
{ "auth_dev_mode": false, "default_user_id": null, "default_roles": null }
```

---

## FastAPI dependencies

### `get_current_user`

Defined in `app/services/auth.py`. Inject this to require authentication:

```python
from ..services.auth import CurrentUser, get_current_user

@router.get("/something")
def something(current_user: CurrentUser = Depends(get_current_user)):
    ...
```

**Resolution order:**

1. If `Authorization: Bearer <token>` is present → validate the JWT, look up the user in the DB, return a `CurrentUser`.
2. If no `Authorization` header **and** `AUTH_DEV_MODE=true` → build a `CurrentUser` from `X-User-Id` / `X-User-Roles` headers (or configured defaults).
3. Otherwise → `401 Unauthorized`.

`CurrentUser` fields:

| Field | Type | Description |
|---|---|---|
| `id` | `str` | User ID (UUID string) |
| `roles` | `set[RoleName]` | Roles granted to this user |
| `username` | `str \| None` | Display name (None for dev overrides) |
| `is_dev_override` | `bool` | True when identity came from dev headers |

Helper methods: `.has(role)`, `.has_any(*roles)`.

---

### `get_optional_user`

Same as `get_current_user` but returns `None` instead of raising `401` when the request is unauthenticated. Use this for endpoints that support both anonymous and authenticated access.

```python
from ..services.auth import CurrentUser, get_optional_user

@router.get("/public")
def public(current_user: CurrentUser | None = Depends(get_optional_user)):
    if current_user:
        ...
```

---

## Role system

Roles are stored in the `roles` table and assigned to users via the `user_roles` join table.

| Role | Value | Capabilities |
|---|---|---|
| `ADMIN` | `admin` | Everything — bypasses all role checks |
| `WORKFLOW_CREATOR` | `workflow_creator` | Create/edit workflows, set model URLs |
| `JOB_CREATOR` | `job_creator` | Submit jobs from published workflows |
| `MODERATOR` | `moderator` | Review assets, approve/reject model URLs |
| `VIEWER` | `viewer` | Read approved assets |

ADMIN is a superrole: `require_any_role()` always passes for ADMIN users regardless of which roles are listed.

---

## `require_any_role()` helper

Defined in `app/services/auth.py`. Use this inside route handlers to assert roles after injecting `get_current_user`:

```python
from ..services.auth import CurrentUser, get_current_user, require_any_role
from ..models import RoleName

@router.post("/admin-only")
def admin_only(current_user: CurrentUser = Depends(get_current_user)):
    require_any_role(current_user, RoleName.ADMIN, RoleName.MODERATOR)
    ...
```

Raises `403 Forbidden` if the user has none of the listed roles (ADMIN always passes).

---

## Security notes

- **Passwords** — hashed with PBKDF2-SHA256 via `passlib`. No 72-byte limit.
- **Refresh tokens** — 48-byte random URL-safe values (`secrets.token_urlsafe(48)`), stored as SHA-256 hashes. The plaintext value is never persisted.
- **Token rotation** — every `/refresh` call revokes the presented token and issues a new one. Reuse of a revoked token returns `401`.
- **Rate limiting** — `/login` is rate-limited to 10 requests/minute via `slowapi`.
- **SQLite datetime caveat** — SQLite stores `DATETIME` without timezone info. `record.expires_at` is returned as a naive datetime. The comparison uses `.replace(tzinfo=UTC)` to restore the UTC label before comparing to `datetime.now(UTC)`. This is forward-compatible with Postgres, where `TIMESTAMPTZ` returns timezone-aware datetimes and `.replace()` becomes a no-op.
