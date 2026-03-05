# Assets Lifecycle

## Overview
Assets are generated outputs produced by ComfyUI jobs and ingested by the backend worker into app-owned storage.  
The backend DB is the source of truth for asset metadata, moderation status, and export state.

## End-to-End Flow
1. A user creates a job via `POST /api/jobs`.
2. Worker picks `QUEUED` jobs, submits prompt to ComfyUI (`POST /prompt`), stores `comfy_job_id`.
3. Worker polls ComfyUI job detail (`GET /api/jobs/{comfy_job_id}`).
4. When ComfyUI status is `completed`, worker:
   - reads `outputs` from job detail,
   - downloads each output with ComfyUI `GET /view?filename=...&subfolder=...&type=...`,
   - writes files into app storage (`STORAGE_ROOT/jobs/<job_id>/outputs/`),
   - computes SHA-256 + size,
   - inserts `assets` rows,
   - inserts `asset_validation_current` row as `PENDING`.
5. Job is marked `GENERATED` if ingestion succeeds; otherwise `FAILED` with `error_message`.

## Storage Layout
- Workflow snapshot used for execution:
  - `STORAGE_ROOT/jobs/<job_id>/workflow_used.json`
- Ingested outputs:
  - `STORAGE_ROOT/jobs/<job_id>/outputs/<asset_id>.<ext>`

ComfyUI output folders are treated as transient executor storage; ingested files in `STORAGE_ROOT` are app-owned records.

## Data Model Links
- `jobs (1) -> (many) assets`
- `workflows (1) -> (many) assets` (through `workflow_id`)
- `workflow_versions (1) -> (many) assets` (through `workflow_version_id`)
- `assets (1) -> (1) asset_validation_current`
- `assets (1) -> (many) asset_validations` (history)
- `assets (1) -> (0/1) asset_exports`

## API Endpoints
- List assets: `GET /api/assets`
- Get asset detail: `GET /api/assets/{asset_id}`
- Download asset: `GET /api/assets/{asset_id}/download`
- Review asset (moderation): `POST /api/assets/{asset_id}/review`
- Export asset: `POST /api/assets/{asset_id}/export`

## Access Rules
- `ADMIN`: can see/download all assets.
- `MODERATOR`: can see/download all assets, can review, can export.
- Others (`VIEWER`, etc.):
  - only see/download assets with current validation status `APPROVED`.
  - if not approved, API returns `403`.

## Operational Notes
- Worker must be running for ingestion to occur.
- Completed jobs created before ingestion logic was deployed will not auto-backfill assets.
- `STORAGE_ROOT` must be writable by the worker process.
  - Local dev should set `STORAGE_ROOT` to a local writable path (not `/data/app` unless mounted/owned).

## Known Gaps
- No automatic backfill command for old completed jobs yet.
- No deduplication across jobs (same file content still creates distinct asset rows).
- Export endpoint currently records metadata; full export packaging pipeline is minimal.
