# Authorization Integration Pipeline

This document describes how external clients (web apps, scripts, other machines) should authenticate and call the backend API.

## 1. Login (Obtain Tokens)
Call:

- `POST /api/auth/login`

Request body:

```json
{
  "username": "admin",
  "password": "admin123"
}
```

Response includes:
- `access_token` (JWT, short lived)
- `refresh_token` (opaque, long lived)
- `expires_in_seconds`
- `user`

## 2. Call Protected APIs
For every protected request, send:

- `Authorization: Bearer <access_token>`

Example:

```bash
curl http://127.0.0.1:8000/api/workflows \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

## 3. Refresh on Expiry
When access token expires (typically HTTP `401`), call:

- `POST /api/auth/refresh`

Request body:

```json
{
  "refresh_token": "<REFRESH_TOKEN>"
}
```

This rotates refresh tokens:
- old refresh token becomes revoked
- response returns a new access token + new refresh token

Client must replace both stored tokens.

## 4. Logout
Call:

- `POST /api/auth/logout`

Body:

```json
{
  "refresh_token": "<REFRESH_TOKEN>"
}
```

This revokes the refresh token.

## 5. Verify Session
Use:

- `GET /api/auth/me`

with bearer token to retrieve current user and roles.

## Role Authorization Behavior
Authentication (who you are) is handled by JWT.  
Authorization (what you can do) is enforced by role checks in route dependencies.

Main roles:
- `admin`
- `workflow_creator`
- `job_creator`
- `viewer`
- `moderator`

## Development Override (Local Only)
If `AUTH_DEV_MODE=true` and no `Authorization` header is sent, backend can inject a dev user context.

Optional override headers in dev mode:
- `X-User-Id`
- `X-User-Roles` (comma-separated)

For production/shared environments:
- set `AUTH_DEV_MODE=false`
- require JWT bearer tokens for all clients.

## Recommended Client Strategy
1. Keep `access_token` in memory.
2. Keep `refresh_token` in secure storage (httpOnly cookie preferred for browser apps).
3. Attach bearer token on each API call.
4. On `401`, call refresh once, retry original request.
5. If refresh fails, redirect to login.
