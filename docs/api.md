# API Reference (MVP 1.0)

**Normative contract:** [`architecture/api_contracts.md`](architecture/api_contracts.md).
This page is the implementation summary; if the two disagree, the contract
governs. `docs/specifications/04_backend_specification.md` defines the service
behaviour.

- Base path: `/api/v1`
- Health endpoints live at the root (`/health/*`) and are also reachable through
  the production proxy.
- Content type: `application/json` unless noted.
- Authentication: `session` cookie (HttpOnly, Secure in production,
  `SameSite=Lax`). State-changing methods also require `X-CSRF-Token`, obtained
  from `GET /auth/csrf` after sign-in. The token is bound to the session.
- Errors: `{"error": {"code": "...", "message": "...", "details": ..., "request_id": "..."}}`.
- Development Swagger: `/docs`; OpenAPI: `/openapi.json` (disabled in
  production).

---

## Health

| Method | Path | Response |
|---|---|---|
| GET | `/health/live` | `200 {"status":"ok","service":...,"version":"1.0.0"}` |
| GET | `/health/ready` | `200` when PostgreSQL answers, `503` otherwise |
| GET | `/health/dependencies` | `200` with `database`/`redis` status; never fails |

## Authentication

| Method | Path | Success | Notes |
|---|---|---|---|
| POST | `/api/v1/auth/register` | `201 {"user": ...}` | Sets `session` and `csrf_token` cookies; `429 RATE_LIMITED` with `Retry-After` after repeated attempts |
| POST | `/api/v1/auth/login` | `200 {"user": ...}` | Generic `401` for bad credentials or inactive accounts; rate limited |
| POST | `/api/v1/auth/logout` | `204` | Requires `X-CSRF-Token`; revokes the session, clears cookies |
| GET | `/api/v1/auth/me` | `200` user | `401` without a valid session |
| GET | `/api/v1/auth/csrf` | `200 {"csrf_token": ...}` | Requires a session; refreshes the readable CSRF cookie |

## Projects

| Method | Path | Success | Notes |
|---|---|---|---|
| POST | `/api/v1/projects` | `201` Project | CSRF; body `{name, type}`; `type` is `OBJECT` or `SCENE`; status `CREATED` |
| GET | `/api/v1/projects` | `200 {items,total_count,limit,offset}` | `limit` default 20, capped at `MAX_PAGE_SIZE`; filters `type`, `status`, `sort` (`created_at_desc`/`created_at_asc`) |
| GET | `/api/v1/projects/{id}` | `200` Project | `404 PROJECT_NOT_FOUND` for missing, deleted or another user's project |
| DELETE | `/api/v1/projects/{id}` | `202 {project_id,deletion_status}` | CSRF; soft delete, task cancellation, storage cleanup job in one transaction |

Project responses include `source_image_count`, `result_available`,
`current_result` and `latest_task` summaries. No storage key or filesystem path
is ever returned.

## Images

| Method | Path | Success | Notes |
|---|---|---|---|
| POST | `/api/v1/projects/{id}/images` | `201` Image | CSRF; multipart `file`; JPEG/PNG; verified MIME and SHA-256 |
| GET | `/api/v1/projects/{id}/images` | `200 {items,total_count}` | Metadata only, upload order |
| GET | `/api/v1/projects/{id}/images/{image_id}/content` | `200` bytes | Streamed with verified `Content-Type`, `inline` disposition, `Cache-Control: private`, `nosniff` |
| DELETE | `/api/v1/projects/{id}/images/{image_id}` | `204` | CSRF; refuses images used by generation history (`409 IMAGE_REFERENCED`) or while a task is active |

Upload limits: `MAX_UPLOAD_SIZE_MB` (413), `MAX_IMAGE_DIMENSION` (400),
unsupported format (415). An OBJECT project accepts exactly one image; a SCENE
project accepts up to `MAX_SCENE_IMAGES`.

## Generation

| Method | Path | Success | Notes |
|---|---|---|---|
| POST | `/api/v1/projects/{id}/generate` | `202` new / `200` repeat | CSRF + mandatory `Idempotency-Key`; creates task, snapshot, `PENDING` project and outbox event in one transaction |
| GET | `/api/v1/projects/{id}/status` | `200 {project_id,project_status,result_available,latest_task}` | Only persisted status/stage/progress/error fields |

Errors: `409 GENERATION_INPUT_MISSING`, `409 INVALID_PROJECT_STATE`,
`409 GENERATION_ALREADY_RUNNING`, `409 IDEMPOTENCY_KEY_REUSED`. A repeat with the
same key and fingerprint returns the existing task with `200`.

## Results

| Method | Path | Success | Notes |
|---|---|---|---|
| GET | `/api/v1/projects/{id}/result` | `200` Result | Current validated result only: `id`, `project_id`, `task_id`, `format`, `mime_type`, `file_size_bytes`, `metadata`, `is_current`, `created_at`; `404 RESULT_NOT_FOUND` |
| GET | `/api/v1/projects/{id}/download` | `200` GLB | `model/gltf-binary`, 64 KiB chunks, safe `Content-Disposition`, `private, no-store`, `nosniff`, `Content-Length`; `404 RESULT_FILE_MISSING`, `503 STORAGE_UNAVAILABLE` |

A failed regeneration preserves the previous current result. Ownership is
enforced on every result and download request; foreign resources return `404`.
