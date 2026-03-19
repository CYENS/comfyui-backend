# ComfyUI Wrapper Backend (MVP)

This is a sibling backend for ComfyUI. It does not modify ComfyUI.

## What you get
- FastAPI API gateway (jobs, workflows, assets, review, export)
- Simple worker loop (polls DB, submits to ComfyUI)
- SQLite DB (Postgres-compatible schema)

## Run (dev)

1. Create a virtualenv and install deps with `uv`:

```bash
uv sync
```

2. Create env file:

```bash
cp .env.example .env
```

3. Seed everything (roles, system user, default workflows, admin user):

```bash
uv run python -m app.seed
```

You can also seed optional role users via `.env`:
- `WORKFLOW_CREATOR_USER_NAME` / `WORKFLOW_CREATOR_USER_PASSWORD`
- `JOB_CREATOR_USER_NAME` / `JOB_CREATOR_USER_PASSWORD`
- `VIEWER_USER_NAME` / `VIEWER_USER_PASSWORD`
- `MODERATOR_USER_NAME` / `MODERATOR_USER_PASSWORD`

4. Start the API:

```bash
uv run uvicorn app.main:app --reload --port 8000
```

5. Start the worker:

```bash
uv run python -m app.worker
```

## Authentication flow

```mermaid
sequenceDiagram
    participant FE as Frontend
    participant API as Backend API

    Note over FE,API: Startup — detect dev mode
    FE->>API: GET /api/auth/dev
    API-->>FE: { auth_dev_mode, default_user_id, default_roles }

    Note over FE,API: Login
    FE->>API: POST /api/auth/login { username, password }
    API-->>FE: { access_token, refresh_token, expires_in_seconds, user }
    Note over FE: Store access_token in memory<br/>Store refresh_token in httpOnly cookie

    Note over FE,API: Authenticated request
    FE->>API: GET /api/... ── Authorization: Bearer <access_token>
    API-->>FE: 200 OK + data

    Note over FE,API: Silent token refresh (access token expired)
    FE->>API: POST /api/auth/refresh { refresh_token }
    API-->>FE: new { access_token, refresh_token }
    Note over FE: Replace both stored tokens
    FE->>API: retry original request with new access_token
    API-->>FE: 200 OK + data

    Note over FE,API: Logout
    FE->>API: POST /api/auth/logout { refresh_token }
    API-->>FE: { status: "ok" }
    Note over FE: Clear both tokens from storage
```

## Notes
- JWT auth is enabled (`/api/auth/login`, `/api/auth/refresh`, `/api/auth/logout`, `/api/auth/me`).
- Access token lifetime is controlled by `AUTH_ACCESS_TOKEN_TTL_MINUTES` in `backend/.env` (default `60`).
- Development override is available via `AUTH_DEV_MODE=true` for faster local iteration.
- Seeder command reads `USER_NAME` and `USER_PASSWORD` from `.env` (or environment variables).
- Optional headers:
  - `x-user-id: <user-id>`
  - `x-user-roles: admin,workflow_creator,job_creator,viewer,moderator`
- ComfyUI base URL defaults to http://127.0.0.1:8188
- Storage root defaults to /data/app
- The Text→Audio workflow template is loaded from `prompts/audio_stable_audio_example.json`.
- Docs:
  - `docs/AUTHENTICATION.md` — full auth system reference (backend)
  - `docs/auth-frontend-integration.md` — frontend integration guide with TypeScript reference implementation
