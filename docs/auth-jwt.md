# JWT Authentication

## Overview
The backend supports JWT access tokens + rotating refresh tokens.

- Access token: short-lived JWT (`Authorization: Bearer <token>`)
- Refresh token: opaque token stored hashed in DB (`refresh_tokens` table)
- Roles are included in access token claims and enforced by route dependencies.

## Endpoints
- `POST /api/auth/login`
  - body: `{ "username": "...", "password": "..." }`
  - returns access + refresh token pair and user roles.
- `POST /api/auth/refresh`
  - body: `{ "refresh_token": "..." }`
  - revokes old refresh token and issues a new pair.
- `POST /api/auth/logout`
  - body: `{ "refresh_token": "..." }`
  - revokes the refresh token.
- `GET /api/auth/me`
  - requires bearer access token (or dev override mode).
- `GET /api/auth/dev`
  - shows development auth override status.

## Token Claims
Access token claims:
- `sub`: user id
- `roles`: role names
- `iss`: configured issuer
- `iat`: issued-at timestamp
- `exp`: expiry timestamp
- `typ`: `access`

## Config (`backend/.env`)
- `AUTH_JWT_SECRET`
- `AUTH_JWT_ALGORITHM` (default `HS256`)
- `AUTH_ACCESS_TOKEN_TTL_MINUTES` (default `60`)
- `AUTH_REFRESH_TOKEN_TTL_DAYS` (default `14`)
- `AUTH_ISSUER`
- `AUTH_DEV_MODE` (`true`/`false`)
- `AUTH_DEV_USER_ID`
- `AUTH_DEV_USER_ROLES` (comma-separated)

## Development Override
When `AUTH_DEV_MODE=true` and no `Authorization` header is provided:
- backend injects a dev user context
- default roles come from `AUTH_DEV_USER_ROLES`
- optional headers `X-User-Id` / `X-User-Roles` can override the default.

Use this only for local development/testing.

## UI Usage
- `/ui/auth` page allows login/logout and stores tokens in `localStorage`.
- `/ui/workflows`, `/ui/jobs`, `/ui/assets` send bearer token from `localStorage` if present.

## Security Notes
- Set a strong `AUTH_JWT_SECRET` in non-dev environments.
- Disable development override (`AUTH_DEV_MODE=false`) in non-dev environments.
- Refresh tokens are stored hashed (`sha256`) and can be revoked.
