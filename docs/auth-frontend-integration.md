# Frontend Authentication Integration Guide

This document is a complete, self-contained reference for implementing authentication
against the ComfyUI Wrapper Backend. It contains all types, endpoint contracts, storage
recommendations, and a reference implementation. Reading this file is sufficient to
implement a fully working auth client.

---

## How the system works

- **Access token** — short-lived JWT (default 60 min). Sent as `Authorization: Bearer <token>` on every API call.
- **Refresh token** — long-lived opaque token (default 14 days). Used only to obtain new token pairs. Each use rotates it (old token revoked, new one issued). Never send this on normal API calls.
- **Dev mode** — when `auth_dev_mode: true` (returned by `GET /api/auth/dev`), the server accepts requests with no JWT. Identity is taken from `X-User-Id` / `X-User-Roles` headers, or falls back to server-configured defaults. Used for local development only.

---

## TypeScript types

```ts
// User identity returned by login, refresh, and /me
interface AuthUser {
  id: string;
  username: string;
  roles: string[]; // e.g. ["job_creator", "viewer"]
}

// Response shape for login and refresh
interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in_seconds: number;
  refresh_token: string;
  user: AuthUser;
}

// Response shape for GET /api/auth/dev
interface DevStatusResponse {
  auth_dev_mode: boolean;
  default_user_id: string | null;
  default_roles: string[] | null;
}

// In-memory auth state
interface AuthState {
  accessToken: string;
  refreshToken: string;
  expiresAt: Date; // derived from Date.now() + expires_in_seconds * 1000
  user: AuthUser;
}
```

---

## Endpoints

Base URL: `http://<host>:8000` (or proxied path in production).

### `GET /api/auth/dev`

No auth required. Call this on app startup to detect dev mode.

```
GET /api/auth/dev
```

Response `200`:
```json
{
  "auth_dev_mode": false,
  "default_user_id": null,
  "default_roles": null
}
```

---

### `POST /api/auth/login`

Rate-limited to 10 requests/minute per IP.

```
POST /api/auth/login
Content-Type: application/json

{ "username": "alice", "password": "secret" }
```

Response `200` → `TokenResponse`

Errors:
- `401` — wrong credentials

---

### `POST /api/auth/refresh`

Exchange a valid refresh token for a new token pair. The submitted refresh token is
immediately revoked; reuse returns `401`.

```
POST /api/auth/refresh
Content-Type: application/json

{ "refresh_token": "<opaque>" }
```

Response `200` → `TokenResponse`

Errors:
- `401` — token not found, already revoked, or expired

---

### `POST /api/auth/logout`

Revoke a refresh token. Idempotent — always returns `200` even if the token is unknown.

```
POST /api/auth/logout
Content-Type: application/json

{ "refresh_token": "<opaque>" }
```

Response `200`:
```json
{ "status": "ok" }
```

---

### `GET /api/auth/me`

Returns the authenticated user. Useful for verifying a stored token is still valid on app
startup.

```
GET /api/auth/me
Authorization: Bearer <access_token>
```

Response `200` → `AuthUser`

Errors:
- `401` — missing, invalid, or expired access token

---

## Token storage recommendations

| Token | Where to store | Why |
|---|---|---|
| `access_token` | JavaScript memory (module-level variable) | Short-lived; never needs to survive page reload; keeping it out of storage prevents XSS exfiltration |
| `refresh_token` | `httpOnly` cookie (set by your BFF/server) or `localStorage` | Needs to survive page reload; `httpOnly` prevents JS access |

If you have no server-side component, storing the refresh token in `localStorage` is
acceptable for internal tooling. Do not do this for user-facing production apps.

---

## Implementation: reference client (TypeScript)

```ts
const API_BASE = "http://localhost:8000";

let auth: AuthState | null = null;
let refreshPromise: Promise<AuthState> | null = null;

// ── Public API ──────────────────────────────────────────────────────────────

export async function login(username: string, password: string): Promise<AuthUser> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new AuthError(res.status, await res.text());
  const data: TokenResponse = await res.json();
  auth = tokenResponseToState(data);
  persistRefreshToken(auth.refreshToken);
  return data.user;
}

export async function logout(): Promise<void> {
  if (!auth) return;
  await fetch(`${API_BASE}/api/auth/logout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: auth.refreshToken }),
  });
  auth = null;
  clearRefreshToken();
}

// Restore session on page load without forcing a login page
export async function restoreSession(): Promise<AuthUser | null> {
  const stored = loadRefreshToken();
  if (!stored) return null;
  try {
    auth = await doRefresh(stored);
    return auth.user;
  } catch {
    clearRefreshToken();
    return null;
  }
}

// Authenticated fetch — use this instead of raw fetch() for all API calls.
// Automatically refreshes the access token if it has expired.
export async function apiFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const token = await getValidAccessToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...init.headers,
      Authorization: `Bearer ${token}`,
    },
  });
  if (res.status === 401) {
    // Access token was rejected (e.g. server restarted with new secret).
    // Attempt one silent refresh and retry.
    try {
      const freshToken = await silentRefresh();
      return fetch(`${API_BASE}${path}`, {
        ...init,
        headers: {
          ...init.headers,
          Authorization: `Bearer ${freshToken}`,
        },
      });
    } catch {
      auth = null;
      clearRefreshToken();
      throw new AuthError(401, "Session expired — please log in again");
    }
  }
  return res;
}

// ── Dev mode helper ──────────────────────────────────────────────────────────

export async function getDevStatus(): Promise<DevStatusResponse> {
  const res = await fetch(`${API_BASE}/api/auth/dev`);
  return res.json();
}

// In dev mode, skip login and inject identity headers directly.
export function devFetch(
  path: string,
  init: RequestInit = {},
  userId = "dev-admin",
  roles = "admin"
): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...init.headers,
      "X-User-Id": userId,
      "X-User-Roles": roles,
    },
  });
}

// ── Internal helpers ─────────────────────────────────────────────────────────

async function getValidAccessToken(): Promise<string> {
  if (!auth) throw new AuthError(401, "Not authenticated");
  // Proactively refresh if the access token expires within the next 60 seconds
  if (auth.expiresAt <= new Date(Date.now() + 60_000)) {
    auth = await silentRefresh();
  }
  return auth.accessToken;
}

// Coalesces concurrent refresh calls into one request
function silentRefresh(): Promise<AuthState> {
  if (refreshPromise) return refreshPromise;
  if (!auth) return Promise.reject(new AuthError(401, "Not authenticated"));
  refreshPromise = doRefresh(auth.refreshToken).finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

async function doRefresh(refreshToken: string): Promise<AuthState> {
  const res = await fetch(`${API_BASE}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) throw new AuthError(res.status, await res.text());
  const data: TokenResponse = await res.json();
  const state = tokenResponseToState(data);
  persistRefreshToken(state.refreshToken);
  return state;
}

function tokenResponseToState(data: TokenResponse): AuthState {
  return {
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    expiresAt: new Date(Date.now() + data.expires_in_seconds * 1000),
    user: data.user,
  };
}

// ── Token persistence (adapt to your storage strategy) ──────────────────────

const REFRESH_TOKEN_KEY = "comfyui_refresh_token";

function persistRefreshToken(token: string): void {
  localStorage.setItem(REFRESH_TOKEN_KEY, token);
}

function loadRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

function clearRefreshToken(): void {
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

// ── Error type ───────────────────────────────────────────────────────────────

export class AuthError extends Error {
  constructor(
    public readonly status: number,
    message: string
  ) {
    super(message);
    this.name = "AuthError";
  }
}
```

---

## Startup sequence (recommended)

```ts
async function init() {
  // 1. Check dev mode — skip login UI in local development
  const { auth_dev_mode } = await getDevStatus();
  if (auth_dev_mode) {
    console.info("Dev mode active — skipping login");
    return; // use devFetch() for all calls
  }

  // 2. Try to restore an existing session from a persisted refresh token
  const user = await restoreSession();
  if (user) {
    console.info("Session restored for", user.username);
    return; // use apiFetch() for all calls
  }

  // 3. No session — redirect to login page
  showLoginPage();
}
```

---

## Error handling reference

| Status | Endpoint | Meaning | Action |
|---|---|---|---|
| `401` | `/login` | Wrong credentials | Show error to user |
| `401` | `/refresh` | Refresh token expired or revoked | Clear session, redirect to login |
| `401` | any `/api/*` | Access token invalid/expired | Silent refresh, then retry once |
| `403` | any `/api/*` | Authenticated but insufficient role | Show "access denied" |
| `429` | `/login` | Rate limit hit (10/min) | Back off, show retry message |

---

## Roles reference

Roles are returned as lowercase strings in the `user.roles` array.

| Value | Capabilities |
|---|---|
| `admin` | Everything — bypasses all role checks |
| `workflow_creator` | Create/edit workflows, set model download URLs |
| `job_creator` | Submit jobs from published workflows |
| `moderator` | Review assets, approve/reject model download URLs |
| `viewer` | Read approved assets |

`admin` is a superrole — a user with `admin` passes any role check regardless of what other roles they hold.

---

## Checklist for a working integration

- [ ] Call `GET /api/auth/dev` on startup and branch on `auth_dev_mode`
- [ ] Store the access token in memory only (not `localStorage`)
- [ ] Store the refresh token in an `httpOnly` cookie or, for internal tooling, `localStorage`
- [ ] Wrap all API calls in a function that injects `Authorization: Bearer <access_token>`
- [ ] Proactively refresh the access token ~60 s before `expiresAt`
- [ ] On a `401` from any API call, attempt one silent refresh and retry
- [ ] On a failed refresh, clear session state and redirect to login
- [ ] Call `POST /api/auth/logout` on explicit logout and clear all stored tokens
- [ ] Coalesce concurrent refresh calls (multiple in-flight requests should share one refresh)
