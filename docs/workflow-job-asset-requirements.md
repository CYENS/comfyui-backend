# Workflow, Job, Asset Requirements (Versioned + RBAC)

## 1) Scope

This document compiles product and backend requirements for:
- Workflow management (with versioning)
- Job execution tracking
- Asset generation and moderation
- Access control via multi-role users
- Data model and migration approach

The system is a wrapper around ComfyUI. ComfyUI is execution-only. The wrapper DB is source of truth.

## 2) Actors and Roles

A user can have one or more roles.

Roles:
- `admin`
- `workflow_creator`
- `job_creator`
- `viewer`
- `moderator` (needed for moderation workflow)

### 2.1 Role Capabilities

`admin`:
- Full access to all entities and actions.
- Can create/edit/delete any workflow.
- Can force lifecycle operations including destructive ones.

`workflow_creator`:
- Can create new workflows.
- Can edit own workflows.
- Can duplicate workflows created by others.
- Cannot edit/delete workflows not owned by them.

`job_creator`:
- Can create jobs from any published/active workflow.
- Can list/view own jobs and related assets (subject to asset visibility policy).

`viewer`:
- Can list/view only validated/approved assets.
- Can browse workflows intended for consumption.

`moderator`:
- Can view all assets (approved + pending + rejected).
- Can validate/reject assets and leave notes.

## 3) Workflow Model with Versioning

Requirement: keep provenance and avoid breaking links from historical jobs/assets to workflow definitions.

Adopt immutable version records.

### 3.1 Entities

`workflows` (logical workflow identity):
- Stable identity across revisions.
- Ownership and lineage metadata.

`workflow_versions` (immutable content revisions):
- One row per version.
- Stores prompt JSON and input schema used by jobs.
- Jobs reference this table directly.

### 3.2 Behavior

- Creating a workflow creates:
  - `workflows` row
  - first `workflow_versions` row (version number = 1)
- Editing a workflow creates a NEW `workflow_versions` row.
- "Current version" is tracked on `workflows.current_version_id`.
- Duplicating a workflow creates a new `workflows` row with lineage:
  - `workflows.parent_workflow_id = source_workflow_id`
  - first version cloned from source current version.

### 3.3 Delete semantics

Non-admin:
- Delete allowed only if workflow has no jobs/assets across any version.

Admin:
- May delete workflow regardless of usage.
- Deleting workflow cascades to:
  - workflow versions
  - jobs referencing those versions
  - assets from those jobs
  - validations related to those assets

## 4) Job Requirements

Each job tracks how output was produced.

Job fields:
- Internal job ID
- ComfyUI job/prompt ID
- User ID (who initiated)
- Workflow version ID (exact version used)
- Start time
- End time
- Status (`QUEUED`, `SUBMITTED`, `RUNNING`, `GENERATED`, `FAILED`, `CANCELLED`)
- Error (optional)

Progress:
- Runtime/transient only, not persisted.

### 4.1 Job Inputs

Store actual runtime input values per job.

`job_input_values`:
- `job_id`
- `input_id`
- `value_json`
- unique `(job_id, input_id)`

## 5) Asset Requirements

- One job can generate many assets.
- One asset belongs to exactly one job.
- Asset must be traceable to workflow version and user.

Asset provenance:
- `asset.job_id -> jobs.user_id`
- `asset.job_id -> jobs.workflow_version_id`

Store:
- path, media type, size, checksum
- generation timestamps

### 5.1 Moderation / Validation

Need moderation data per asset, including who validated and when.

Use history + current-state model:

`asset_validations` (append-only history):
- `asset_id`
- `moderator_user_id`
- `status` (`PENDING`, `APPROVED`, `REJECTED`)
- `notes`
- `validated_at`

`asset_validation_current` (fast access snapshot):
- `asset_id`
- `status`
- `moderator_user_id`
- `validated_at`
- `notes`

Visibility policy:
- `viewer`, `job_creator`, `workflow_creator`: only `APPROVED` assets unless they also have `moderator` or `admin`.
- `moderator`, `admin`: all assets.

## 6) Required Queries / Views

1. Workflow table listing
- all logical workflows with owner, current version, updated_at.

2. Workflow experiments table
- for a given workflow version set:
  - jobs + input values + produced assets
- supports "inputs vs outputs" analysis.

3. Assets by workflow
- all assets generated from any version of a workflow.

4. Assets by status
- approved-only catalog for non-moderator users.

## 7) SQLAlchemy Target Schema

## 7.1 Users and Roles

`users`
- `id` PK
- `username` unique
- `password_hash`
- timestamps

`roles`
- `id` PK
- `name` unique (`admin`, `workflow_creator`, `job_creator`, `viewer`, `moderator`)

`user_roles`
- `user_id` FK -> users
- `role_id` FK -> roles
- PK (`user_id`, `role_id`)

## 7.2 Workflows

`workflows`
- `id` PK
- `key` unique
- `name`
- `description`
- `created_by_user_id` FK -> users
- `parent_workflow_id` FK -> workflows nullable
- `current_version_id` FK -> workflow_versions nullable (set after version insert)
- `is_active` bool
- timestamps

`workflow_versions`
- `id` PK
- `workflow_id` FK -> workflows (ON DELETE CASCADE)
- `version_number` int
- `prompt_json` JSON
- `inputs_schema_json` JSON
- `prompt_hash` string
- `created_by_user_id` FK -> users
- `change_note` text nullable
- `is_published` bool
- timestamps
- unique (`workflow_id`, `version_number`)

## 7.3 Jobs

`jobs`
- `id` PK
- `comfy_job_id` nullable index
- `user_id` FK -> users
- `workflow_id` FK -> workflows
- `workflow_version_id` FK -> workflow_versions
- `status` enum
- `start_time` nullable
- `end_time` nullable
- `error_message` nullable
- timestamps

`job_input_values`
- `id` PK
- `job_id` FK -> jobs (ON DELETE CASCADE)
- `input_id` string
- `value_json` JSON
- unique (`job_id`, `input_id`)

## 7.4 Assets and Validation

`assets`
- `id` PK
- `job_id` FK -> jobs (ON DELETE CASCADE)
- `workflow_id` FK -> workflows
- `workflow_version_id` FK -> workflow_versions
- `file_path`
- `media_type`
- `size_bytes`
- `checksum_sha256`
- timestamps

`asset_validations`
- `id` PK
- `asset_id` FK -> assets (ON DELETE CASCADE)
- `moderator_user_id` FK -> users
- `status` enum
- `notes` nullable
- `validated_at`

`asset_validation_current`
- `asset_id` PK/FK -> assets (ON DELETE CASCADE)
- `status` enum
- `moderator_user_id` FK -> users nullable
- `validated_at` nullable
- `notes` nullable

## 8) Authorization Rules (enforced in service layer)

Workflow create:
- requires role `workflow_creator` or `admin`.

Workflow edit:
- `admin`: always.
- `workflow_creator`: only if workflow.owner == user.
- Edit creates new workflow version.

Workflow duplicate:
- `workflow_creator` or `admin`.
- Always allowed for readable workflows.

Workflow delete:
- `admin`: always (cascade).
- non-admin: only if no jobs/assets linked.

Job create:
- `job_creator` or `admin`.

Asset validation:
- `moderator` or `admin`.

Asset read:
- all authenticated roles can read approved assets.
- moderators/admin can read any.

## 9) Migration Plan

Use Alembic with forward-only migrations.

Migration set:
1. Create role tables (`roles`, `user_roles`) and seed roles.
2. Create `workflows` + `workflow_versions`.
3. Alter/replace `jobs` to reference `workflow_version_id`.
4. Create `job_input_values`.
5. Create/alter `assets` with workflow provenance columns.
6. Create `asset_validations` + `asset_validation_current`.
7. Add indexes and uniqueness constraints.

For existing dev SQLite DB:
- either reset DB in development, or
- write data migration:
  - migrate existing workflow JSON into `workflow_versions(version=1)`.
  - repoint jobs/assets to version 1.

## 10) API Impact (high-level)

- Workflow CRUD should operate on logical workflow + version operations:
  - create workflow
  - create new version
  - list versions
  - set current version
  - duplicate workflow
- Job create accepts `workflow_id` and optional `workflow_version_id`.
  - if omitted, use `workflows.current_version_id`.
- Job detail includes resolved input values and asset outputs.

## 11) Non-Goals (for this phase)

- Real-time progress persistence (progress remains transient)
- Multi-worker scheduler changes (K8s orchestration)
- Advanced moderation policy engine beyond status + notes

## 12) Acceptance Criteria

- Every workflow has creator and immutable versions.
- Every job records initiator, workflow version, and input values.
- Every asset traces back to job, workflow version, and user (via job).
- Validators can review assets with full audit trail.
- Non-moderators only access approved assets.
- RBAC enforces role capabilities described above.
