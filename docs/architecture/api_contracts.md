# API Contracts

## 1. Document Purpose

This document defines the canonical REST API contracts for the 3D generation web application.

It describes:

- API conventions.
- Authentication.
- Session management.
- Request and response formats.
- Project management endpoints.
- Image management endpoints.
- Generation task endpoints.
- Result retrieval.
- File downloading.
- HTTP status codes.
- Error response structures.
- Validation rules.
- Authorization requirements.
- Idempotency behavior.

This document is the single source of truth for frontend/backend communication.

The frontend and backend specifications must follow the contracts defined here.

Any API change must be reflected in this document.

## 2. General API Conventions

### 2.1. Base URL

All API endpoints must use:

`/api/v1`

Example:

`http://localhost:8000/api/v1`

The actual base URL must be configurable through environment variables.

### 2.2. Protocol

Use HTTP for local development.

Use HTTPS in production.

### 2.3. Data Formats

Use JSON for ordinary API requests and responses.

Use multipart/form-data for image uploads.

Use binary HTTP responses for generated model downloads and authorized image content retrieval.

### 2.4. Naming Convention

All JSON request and response fields must use snake_case.

Example:

```json
{
  "project_id": "uuid",
  "created_at": "2026-11-05T12:00:00Z",
  "result_available": true
}
```

The frontend may transform API DTOs into camelCase domain models.

Do not expose different field naming conventions in different API modules.

### 2.5. Identifiers

Use UUIDs represented as strings.

Example:

```text
550e8400-e29b-41d4-a716-446655440000
```

All path parameters representing entity identifiers must be validated as UUIDs.

### 2.6. Timestamps

All timestamps must:

- Use ISO 8601.
- Include timezone information.
- Be stored and returned in UTC.
- Use a consistent format.

Example:

`2026-11-05T12:30:00Z`

### 2.7. Content Types

Use:

`application/json`

for JSON requests and responses.

Use:

`multipart/form-data`

for uploads.

Use:

`model/gltf-binary`

for GLB downloads.

Use the verified image MIME type for image content responses.

### 2.8. API Documentation

FastAPI must generate OpenAPI documentation from the implemented request and response schemas.

The generated OpenAPI specification must be consistent with this document.

### 2.9. Response Consistency

All JSON responses must use explicitly defined Pydantic response schemas.

Do not return arbitrary ORM objects directly.

Do not expose internal database fields or filesystem paths.

## 3. Authentication

### 3.1. Authentication Model

Use server-managed session authentication with HttpOnly cookies.

The backend generates a cryptographically random session token.

The raw token is sent to the browser through an HttpOnly cookie.

Only the hash of the session token is stored in PostgreSQL.

### 3.2. Cookie Configuration

Cookie name:

`session`

Required properties:

| Property | Value |
|---|---|
| HttpOnly | true |
| Secure | true in production |
| SameSite | Lax |
| Path | / |
| Max-Age | Configurable |
| Domain | Omitted unless required |

The Secure attribute may be disabled in local HTTP development.

Production must use HTTPS.

The application uses two cookies:

| Cookie | HttpOnly | Purpose |
|---|---|---|
| `session` | true | Authentication |
| `csrf_token` | false | CSRF validation |

The `csrf_token` cookie must be signed, must be bound to the authenticated session and must be readable by the frontend so it can populate the `X-CSRF-Token` header.

### 3.3. CSRF Protection

All authenticated state-changing requests must include:

`X-CSRF-Token`

The token must be associated with the authenticated session.

The token is delivered through a separate non-HttpOnly `csrf_token` cookie.

The frontend reads the cookie and copies its value into the `X-CSRF-Token` header.

The backend must verify:

- That the header value and the cookie value match.
- The signature of the token.
- That the token is bound to the authenticated session.

The frontend may obtain or refresh the token using:

`GET /api/v1/auth/csrf`

The backend must not store a CSRF token hash in `UserSession`. CSRF state is carried by the signed, session-bound cookie.

Registration and login must additionally validate the allowed request Origin and use secure SameSite cookie settings.

The backend must never treat the CSRF token as an authentication credential.

### 3.4. Cookie and CORS Requirements

The browser must send credentials for authenticated API requests.

The frontend HTTP client must use the appropriate credential configuration.

Credentialed CORS requests must use explicitly allowed origins.

Wildcard CORS origins must not be used with credentials.

### 3.5. Authentication Error

If a session is missing, expired or revoked, protected endpoints must return HTTP 401.

---

## 4. API Overview

### 4.1. Authentication Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/register` | Register a user |
| POST | `/auth/login` | Authenticate |
| POST | `/auth/logout` | End session |
| GET | `/auth/me` | Get current user |
| GET | `/auth/csrf` | Obtain session CSRF token |

### 4.2. Project Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/projects` | Create project |
| GET | `/projects` | List projects |
| GET | `/projects/{project_id}` | Get project |
| DELETE | `/projects/{project_id}` | Delete project |

### 4.3. Image Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/projects/{project_id}/images` | Upload one photograph |
| GET | `/projects/{project_id}/images` | List photographs |
| GET | `/projects/{project_id}/images/{image_id}/content` | Retrieve photograph |
| DELETE | `/projects/{project_id}/images/{image_id}` | Delete photograph |

### 4.4. Generation Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/projects/{project_id}/generate` | Start generation |
| GET | `/projects/{project_id}/status` | Get current processing status |

### 4.5. Result Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/projects/{project_id}/result` | Get current result metadata |
| GET | `/projects/{project_id}/download` | Download generated GLB |

---

## 5. Common Data Structures

### 5.1. User Response

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "created_at": "2026-11-05T12:00:00Z"
}
```

Do not expose password hashes, session token hashes or internal authentication metadata.

### 5.2. Project Types

Supported values:

```text
OBJECT
SCENE
```

### 5.3. Project Statuses

Supported values:

```text
CREATED
UPLOADING
PENDING
PROCESSING
COMPLETED
FAILED
```

### 5.4. Generation Task Statuses

Supported values:

```text
PENDING
PROCESSING
COMPLETED
FAILED
CANCELLED
```

`CANCELLED` is an internal terminal state. It is normally not reachable through ordinary user scenarios in the MVP.

### 5.5. Generation Task Stages

Object generation:

```text
IMAGE_PREPARATION
MODEL_GENERATION
MODEL_EXPORT
RESULT_VALIDATION
```

Scene reconstruction:

```text
IMAGE_PREPARATION
FEATURE_EXTRACTION
FEATURE_MATCHING
SPARSE_RECONSTRUCTION
RECONSTRUCTION_VALIDATION
IMAGE_UNDISTORTION
OPENMVS_IMPORT
DENSE_RECONSTRUCTION
MESH_GENERATION
MESH_REFINEMENT
TEXTURING
ASSET_EXPORT
RESULT_VALIDATION
```

`COMPLETED`, `FAILED` and `CANCELLED` are task statuses, not stages. They must not appear in the `stage` field.

### 5.6. Image Response

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "original_filename": "room_01.jpg",
  "mime_type": "image/jpeg",
  "file_size_bytes": 2048000,
  "width": 1920,
  "height": 1080,
  "position": 0,
  "created_at": "2026-11-05T12:00:00Z"
}
```

### 5.7. Generation Task Response

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440002",
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_type": "OBJECT",
  "status": "PROCESSING",
  "stage": "MODEL_GENERATION",
  "progress_percent": null,
  "status_message": "Generating 3D geometry",
  "error_code": null,
  "error_message": null,
  "created_at": "2026-11-05T12:00:00Z",
  "started_at": "2026-11-05T12:00:05Z",
  "finished_at": null
}
```

`progress_percent` must be null when a reliable percentage cannot be determined.

`stage` and `status_message` must describe actual processing information.

### 5.8. Generation Result Response

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440003",
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_id": "550e8400-e29b-41d4-a716-446655440002",
  "format": "GLB",
  "mime_type": "model/gltf-binary",
  "file_size_bytes": 12500000,
  "metadata": {
    "vertices_count": 125000,
    "faces_count": 83000,
    "meshes_count": 1
  },
  "is_current": true,
  "created_at": "2026-11-05T12:10:00Z"
}
```

Optional metadata fields may be omitted when unavailable.

Do not expose `storage_key` or an absolute filesystem path.

### 5.9. Project Response

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My 3D Project",
  "type": "OBJECT",
  "status": "COMPLETED",
  "source_image_count": 1,
  "result_available": true,
  "current_result": {
    "id": "550e8400-e29b-41d4-a716-446655440003",
    "format": "GLB",
    "file_size_bytes": 12500000,
    "created_at": "2026-11-05T12:10:00Z"
  },
  "latest_task": {
    "id": "550e8400-e29b-41d4-a716-446655440002",
    "status": "COMPLETED"
  },
  "created_at": "2026-11-05T12:00:00Z",
  "updated_at": "2026-11-05T12:10:00Z"
}
```

`current_result` and `latest_task` may be null.

`result_available` is independent of project status.

For example, a project may have `status = FAILED` while `result_available = true` because a previous generation succeeded.

### 5.10. Result Availability Structure

The following fragment is common to project and status responses:

```json
{
  "result_available": true,
  "current_result": {
    "id": "uuid",
    "format": "GLB"
  },
  "latest_task": {
    "id": "uuid",
    "status": "FAILED"
  }
}
```

`current_result` and `latest_task` may be null.

`result_available` describes whether a current, successfully validated result exists. It does not describe the latest task outcome.

A project can simultaneously have `project_status = FAILED` and `result_available = true` when a previous generation succeeded and the latest regeneration failed.

Clients must use `result_available` and `current_result` instead of inferring availability from project status.

---

## 6. Authentication API

### 6.1. Register User

Endpoint:

`POST /api/v1/auth/register`

Purpose:

Create a new user account.

Request:

```json
{
  "email": "user@example.com",
  "password": "SecurePassword123!"
}
```

Requirements:

- Validate email.
- Normalize email to lowercase.
- Validate password requirements.
- Check email uniqueness.
- Hash the password.
- Create the user.
- Create an authenticated session.
- Set the HttpOnly session cookie.

Successful response:

HTTP 201 Created.

```json
{
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "created_at": "2026-11-05T12:00:00Z"
  }
}
```

The frontend must not send `password_confirmation` to the backend. Password confirmation is a client-side form validation field.

Possible errors:

- 400 — email already registered.
- 422 — validation error.
- 429 — rate limit exceeded.

### 6.2. Login

Endpoint:

`POST /api/v1/auth/login`

Request:

```json
{
  "email": "user@example.com",
  "password": "SecurePassword123!"
}
```

Successful response:

HTTP 200 OK.

```json
{
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "created_at": "2026-11-05T12:00:00Z"
  }
}
```

The response must also set the session cookie.

Possible errors:

- 401 — invalid credentials.
- 422 — validation error.
- 429 — rate limit exceeded.

Use a generic invalid credentials message.

### 6.3. Logout

Endpoint:

`POST /api/v1/auth/logout`

Requirements:

- Validate the active session.
- Validate CSRF token.
- Revoke the session.
- Clear the session cookie.

Successful response:

HTTP 204 No Content.

### 6.4. Current User

Endpoint:

`GET /api/v1/auth/me`

Successful response:

HTTP 200 OK.

Returns User Response.

If the user is not authenticated:

HTTP 401 Unauthorized.

### 6.5. Obtain CSRF Token

Endpoint:

`GET /api/v1/auth/csrf`

Requires an authenticated session.

Successful response:

HTTP 200 OK.

```json
{
  "csrf_token": "session-bound-csrf-token"
}
```

The backend signs the token, binds it to the session and sets the non-HttpOnly `csrf_token` cookie.

The frontend must send the token in the `X-CSRF-Token` header for authenticated state-changing requests, and the backend verifies it against the cookie and the session.

If the session is invalid:

HTTP 401 Unauthorized.

---

## 7. Project API

### 7.1. Create Project

Endpoint:

`POST /api/v1/projects`

Requires authentication and CSRF validation.

Request:

```json
{
  "name": "My 3D Project",
  "type": "OBJECT"
}
```

Supported project types:

- OBJECT.
- SCENE.

Successful response:

HTTP 201 Created.

Returns Project Response.

Requirements:

- Associate the project with the authenticated user.
- Generate a UUID.
- Set initial status to CREATED.
- Do not start generation automatically.

Possible errors:

- 401 — unauthenticated.
- 422 — invalid request.
- 429 — rate limit exceeded.

### 7.2. List Projects

Endpoint:

`GET /api/v1/projects`

Query parameters:

| Parameter | Type | Required | Description |
|---|---|---|---|
| limit | Integer | No | Number of records |
| offset | Integer | No | Pagination offset |
| type | String | No | OBJECT or SCENE |
| status | String | No | Project status |
| sort | String | No | Sorting order |

Defaults:

```text
limit=20
offset=0
sort=created_at_desc
```

Maximum pagination limit must be configurable.

Successful response:

HTTP 200 OK.

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "My 3D Project",
      "type": "OBJECT",
      "status": "COMPLETED",
      "source_image_count": 1,
      "result_available": true,
      "current_result": {
        "id": "550e8400-e29b-41d4-a716-446655440003",
        "format": "GLB",
        "file_size_bytes": 12500000,
        "created_at": "2026-11-05T12:10:00Z"
      },
      "latest_task": {
        "id": "550e8400-e29b-41d4-a716-446655440002",
        "status": "COMPLETED"
      },
      "created_at": "2026-11-05T12:00:00Z",
      "updated_at": "2026-11-05T12:10:00Z"
    }
  ],
  "total_count": 1,
  "limit": 20,
  "offset": 0
}
```

Return only projects belonging to the authenticated user.

### 7.3. Get Project

Endpoint:

`GET /api/v1/projects/{project_id}`

Successful response:

HTTP 200 OK.

Returns Project Response.

Possible errors:

- 401 — unauthenticated.
- 404 — project not found or inaccessible.

### 7.4. Delete Project

Endpoint:

`DELETE /api/v1/projects/{project_id}`

Requires authentication and CSRF validation.

The backend must:

1. Verify ownership.
2. Prevent new processing operations.
3. Mark the project with `deleted_at`; it becomes inaccessible immediately.
4. Move `PENDING` generation tasks to `CANCELLED`.
5. Set `cancel_requested_at` on `PROCESSING` tasks so workers stop cooperatively.
6. Create a cleanup job for the project root directory `projects/{project_id}/`.
7. Return an accepted deletion response.

Successful response:

HTTP 202 Accepted.

```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "deletion_status": "PENDING"
}
```

The project must immediately disappear from ordinary project listing and retrieval.

A deleted project cannot be retrieved again through any ordinary project, image, status or result endpoint.

Physical file deletion continues asynchronously.

Cleanup must wait until active workers have stopped using project files. Source files must remain available while a worker is still using them.

Possible errors:

- 401 — unauthenticated.
- 404 — project not found or inaccessible.
- 409 — deletion cannot currently be scheduled.

Repeated deletion requests must not create duplicate cleanup operations.

---

## 8. Image API

### 8.1. Upload Image

Endpoint:

`POST /api/v1/projects/{project_id}/images`

Requires authentication and CSRF validation.

Content-Type:

`multipart/form-data`

Form fields:

| Field | Type | Required | Description |
|---|---|---|---|
| file | File | Yes | JPEG or PNG photograph |

Each request uploads exactly one photograph.

The backend assigns image `position` within a project. The frontend must not control persistent image ordering through arbitrary position values.

Successful response:

HTTP 201 Created.

Returns Image Response.

Validation requirements:

- Project ownership.
- Project status permits upload.
- File format is JPEG or PNG.
- File content is a valid image.
- File size does not exceed configured limits.
- Image dimensions are within configured limits.
- Object projects contain no existing source image.
- Scene projects do not exceed the configured image limit.

Possible errors:

- 400 — invalid image.
- 401 — unauthenticated.
- 404 — inaccessible project.
- 409 — project state does not permit uploading.
- 413 — file too large.
- 415 — unsupported media type.
- 422 — validation error.

### 8.2. List Images

Endpoint:

`GET /api/v1/projects/{project_id}/images`

Successful response:

HTTP 200 OK.

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440001",
      "project_id": "550e8400-e29b-41d4-a716-446655440000",
      "original_filename": "room_01.jpg",
      "mime_type": "image/jpeg",
      "file_size_bytes": 2048000,
      "width": 1920,
      "height": 1080,
      "position": 0,
      "created_at": "2026-11-05T12:00:00Z"
    }
  ],
  "total_count": 1
}
```

The endpoint must return only image metadata.

### 8.3. Retrieve Image Content

Endpoint:

`GET /api/v1/projects/{project_id}/images/{image_id}/content`

Requires authentication.

Returns image binary content.

The response must:

- Use the verified MIME type.
- Include a safe Content-Disposition header.
- Avoid exposing the physical storage path.
- Use private caching behavior.
- Verify project ownership.

Possible errors:

- 401 — unauthenticated.
- 404 — image or project not found or inaccessible.
- 500 — storage retrieval failure.

### 8.4. Delete Image

Endpoint:

`DELETE /api/v1/projects/{project_id}/images/{image_id}`

Requires authentication and CSRF validation.

Successful response:

HTTP 204 No Content.

Deletion is allowed only when the source image is not referenced by any generation task and the project is in a state that permits source modification.

The image file and metadata must be removed using the storage cleanup mechanism.

Possible errors:

- 401 — unauthenticated.
- 404 — image or project not found or inaccessible.
- 409 — image is referenced by generation history or project state does not permit deletion.

---

## 9. Generation API

### 9.1. Start Generation

Endpoint:

`POST /api/v1/projects/{project_id}/generate`

Requires authentication and CSRF validation.

Optional JSON body:

```json
{}
```

Required request header:

`Idempotency-Key: <unique-client-generated-value>`

The key must remain unchanged when retrying the same HTTP operation after an uncertain network result.

The key must be different for a new generation operation.

The Idempotency-Key header is mandatory.

The key is scoped to the project.

The same key and the same request fingerprint return the existing task.

The same key with a different request fingerprint returns HTTP 409.

A new user-initiated generation attempt must use a new key.

Internal worker recovery reuses the existing GenerationTask.

The backend must:

1. Authenticate the user.
2. Verify project ownership.
3. Verify project type.
4. Verify source photographs.
5. Validate project state.
6. Check for an existing idempotency key and an active generation task.
7. Compute the request fingerprint from the normalized request.
8. Create a GenerationTask record.
9. Create GenerationTaskImage records.
10. Update the project status to PENDING.
11. Create an OutboxMessage record.
12. Commit all database operations in one transaction.

The task must not execute directly inside the HTTP request.

The Outbox Dispatcher is responsible for subsequent publication to Redis.

Successful response:

HTTP 202 Accepted.

```json
{
  "task": {
    "id": "550e8400-e29b-41d4-a716-446655440002",
    "project_id": "550e8400-e29b-41d4-a716-446655440000",
    "task_type": "OBJECT",
    "status": "PENDING",
    "stage": null,
    "progress_percent": null,
    "status_message": "Generation task accepted",
    "error_code": null,
    "error_message": null,
    "created_at": "2026-11-05T12:00:00Z",
    "started_at": null,
    "finished_at": null
  }
}
```

### 9.2. Idempotency Behavior

If the same project receives a repeated request with the same idempotency key and the same request fingerprint:

- Return the existing task.
- Do not create another GenerationTask.
- Do not create another logical outbox event.

Return HTTP 200 OK when the existing task is returned because of a repeated request.

If the same idempotency key is reused with a different request fingerprint:

- Return HTTP 409 Conflict with `IDEMPOTENCY_KEY_REUSED`.
- Do not create a GenerationTask.

If another active task exists for the project under a different idempotency key:

Return HTTP 409 Conflict with `GENERATION_ALREADY_RUNNING`.

If the project does not have the required images:

Return HTTP 409 Conflict with an appropriate error code.

### 9.3. Get Project Processing Status

Endpoint:

`GET /api/v1/projects/{project_id}/status`

Successful response:

HTTP 200 OK.

```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "project_status": "PROCESSING",
  "result_available": true,
  "latest_task": {
    "id": "550e8400-e29b-41d4-a716-446655440002",
    "task_type": "OBJECT",
    "status": "PROCESSING",
    "stage": "MODEL_GENERATION",
    "progress_percent": null,
    "status_message": "Generating 3D geometry",
    "error_code": null,
    "error_message": null,
    "created_at": "2026-11-05T12:00:00Z",
    "started_at": "2026-11-05T12:00:05Z",
    "finished_at": null
  }
}
```

The latest task may be null when generation has not started.

`result_available` must indicate whether a current successful result exists, regardless of the latest task status.

Possible errors:

- 401 — unauthenticated.
- 404 — project not found or inaccessible.

### 9.4. Processing Stage Semantics

The backend must return the latest actual processing stage.

If progress is not available, return:

```json
{
  "progress_percent": null
}
```

Never fabricate progress percentages.

After COMPLETED, FAILED or CANCELLED:

- `finished_at` must be populated.
- The task stage may contain the last completed processing stage.
- Error fields must be populated only on failure.

---

## 10. Result API

### 10.1. Get Current Result

Endpoint:

`GET /api/v1/projects/{project_id}/result`

Successful response:

HTTP 200 OK.

Returns Generation Result Response.

The endpoint must return the current successful result, not an unvalidated intermediate asset.

If a project has no successful result:

HTTP 404 Not Found.

The response must not expose storage paths.

### 10.2. Download Result

Endpoint:

`GET /api/v1/projects/{project_id}/download`

Requires authentication.

Returns binary GLB content.

Required headers:

```text
Content-Type: model/gltf-binary
Content-Disposition: attachment; filename="<safe-project-name>.glb"
Cache-Control: private, no-store
```

Requirements:

- Verify project ownership.
- Verify a current successful result exists.
- Verify that the file exists.
- Stream the file where appropriate.
- Avoid loading unnecessarily large assets entirely into application memory.
- Use a safe generated download filename.
- Do not disclose internal storage keys.

Possible errors:

- 401 — unauthenticated.
- 404 — project or result not found or inaccessible.
- 503 — storage temporarily unavailable.

---

## 11. HTTP Status Codes

Use standard HTTP semantics.

| Status | Meaning | Application Usage |
|---|---|---|
| 200 | OK | Successful retrieval or idempotent task retrieval |
| 201 | Created | User, project or image created |
| 202 | Accepted | Background processing or deletion accepted |
| 204 | No Content | Successful logout or deletion |
| 400 | Bad Request | Invalid application operation |
| 401 | Unauthorized | Authentication required or invalid |
| 403 | Forbidden | Authenticated request fails a specific access policy |
| 404 | Not Found | Resource absent or intentionally hidden |
| 409 | Conflict | Invalid state or active task conflict |
| 413 | Payload Too Large | File size exceeded |
| 415 | Unsupported Media Type | Unsupported image format |
| 422 | Unprocessable Content | Request validation failed |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Unexpected server error |
| 503 | Service Unavailable | Required dependency unavailable |

For protected project resources belonging to another user, returning 404 is preferred to avoid revealing their existence.

---

## 12. Error Response Format

### 12.1. Standard Error Structure

All API errors must follow:

```json
{
  "error": {
    "code": "INVALID_IMAGE_FORMAT",
    "message": "The uploaded image format is not supported.",
    "details": null,
    "request_id": "request-identifier"
  }
}
```

### 12.2. Field Validation Error

Example:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "One or more fields are invalid.",
    "details": [
      {
        "field": "name",
        "code": "STRING_TOO_SHORT",
        "message": "Project name must not be empty."
      }
    ],
    "request_id": "request-identifier"
  }
}
```

### 12.3. Error Codes

Use stable machine-readable codes.

Examples:

Authentication:

- INVALID_CREDENTIALS.
- SESSION_EXPIRED.
- CSRF_VALIDATION_FAILED.

Projects:

- PROJECT_NOT_FOUND.
- PROJECT_NAME_INVALID.
- INVALID_PROJECT_TYPE.
- PROJECT_ALREADY_DELETED.

Images:

- INVALID_IMAGE_FORMAT.
- INVALID_IMAGE_CONTENT.
- IMAGE_TOO_LARGE.
- IMAGE_DIMENSIONS_EXCEEDED.
- IMAGE_COUNT_EXCEEDED.
- IMAGE_NOT_FOUND.

Generation:

- GENERATION_ALREADY_RUNNING.
- GENERATION_INPUT_MISSING.
- INVALID_PROJECT_STATE.
- GENERATION_FAILED.
- TASK_NOT_FOUND.
- IDEMPOTENCY_KEY_REUSED.
- PROJECT_DELETION_IN_PROGRESS.
- TASK_CANCELLED.
- WORKER_UNAVAILABLE.
- TASK_RECOVERY_IN_PROGRESS.

Results:

- RESULT_NOT_FOUND.
- RESULT_NOT_READY.
- RESULT_FILE_MISSING.

Infrastructure:

- DATABASE_UNAVAILABLE.
- REDIS_UNAVAILABLE.
- STORAGE_UNAVAILABLE.
- INTERNAL_SERVER_ERROR.

Additional error codes may be introduced by the subsystem specifications.

Some codes are primarily diagnostic and internal. `TASK_CANCELLED`, `WORKER_UNAVAILABLE` and `TASK_RECOVERY_IN_PROGRESS` are not necessarily returned by ordinary user-facing endpoints.

### 12.4. Request Identifier

Generate a unique request ID for each incoming request.

Include the request ID in:

- Response error structure.
- Application logs.
- Relevant worker and dispatch logs when available.

Never expose internal stack traces through the API.

---

## 13. Authorization Requirements

Every protected endpoint must validate the authenticated session.

Every project-related endpoint must additionally validate project ownership.

Authorization must cover:

- Project metadata.
- Source images.
- Image content.
- Generation tasks.
- Generation status.
- Result metadata.
- Result downloads.
- Project deletion.

Do not rely on frontend route protection.

Never allow direct user-controlled filesystem paths.

---

## 14. Request Limits and Pagination

### 14.1. Image Upload

Initial development defaults:

```text
MAX_UPLOAD_SIZE_MB=20
MAX_SCENE_IMAGES=100
MIN_SCENE_IMAGES=3
```

These values must be configurable.

The backend is authoritative for all limits.

### 14.2. Project Pagination

Use offset-based pagination for the MVP.

Parameters:

- `limit`
- `offset`

Set a configurable maximum limit.

### 14.3. Request Size

Set request body limits at the API and reverse proxy levels.

Upload limits must be consistent across:

- Frontend validation.
- FastAPI.
- Reverse proxy.
- Storage layer.

### 14.4. Timeouts

File downloads and uploads must use appropriate timeouts.

Background generation must never be tied to the duration of an HTTP request.

---

## 15. API Versioning and Compatibility

### 15.1. Version Prefix

All endpoints must use `/api/v1`.

### 15.2. Backward Compatibility

Avoid removing or changing existing fields in a backward-incompatible manner within the same API version.

Introduce new optional fields when extending responses.

### 15.3. Contract Changes

Any change to:

- URL.
- HTTP method.
- Request schema.
- Response schema.
- Error code.
- Status semantics.
- Authentication behavior.

Must update this document and the corresponding tests.

### 15.4. OpenAPI Validation

The generated FastAPI OpenAPI document must match the API contracts.

Frontend types may be generated from OpenAPI in a later development iteration.

Manual TypeScript DTOs must remain consistent with the canonical JSON schemas.

---

## 16. API Acceptance Criteria

### API-AC-01

All endpoints use the `/api/v1` prefix.

### API-AC-02

All JSON fields use snake_case.

### API-AC-03

All timestamps use UTC ISO 8601 representation.

### API-AC-04

Authentication uses secure session cookies.

### API-AC-05

Authenticated state-changing requests require CSRF validation.

### API-AC-06

All protected resources enforce project ownership.

### API-AC-07

Project creation returns HTTP 201.

### API-AC-08

Image uploading uses multipart/form-data.

### API-AC-09

Generation initiation returns HTTP 202 when a new task is accepted.

### API-AC-10

Repeated generation requests with the same idempotency key do not create duplicate logical tasks. A reused key with a different request fingerprint returns HTTP 409.

### API-AC-11

Conflicting active generation requests return HTTP 409.

### API-AC-12

Task status responses contain actual persisted processing information.

### API-AC-13

Current result availability is independent of the latest task status.

### API-AC-14

Result download returns valid GLB binary content.

### API-AC-15

All JSON errors follow the common error schema.

### API-AC-16

No API response exposes passwords, session hashes or physical storage paths.

### API-AC-17

OpenAPI documentation is consistent with the implemented contracts.

---

## 17. Related Specifications

- `00_project_overview.md`
- `01_product_requirements.md`
- `03_frontend_specification.md`
- `04_backend_specification.md`
- `05_database_specification.md`
- `06_object_generation.md`
- `07_scene_reconstruction.md`
- `08_infrastructure.md`
- `09_testing.md`
- `10_development_roadmap.md`
- `architecture/system_architecture.md`
- `architecture/data_flow.md`
- `AI_DEVELOPMENT_GUIDE.md` — development workflow and agent rules.