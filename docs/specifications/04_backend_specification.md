# 04 — Backend Specification

## 1. Document Purpose

This document defines the backend architecture and implementation requirements for the 3D generation web application.

It describes:
- Backend architecture and module responsibilities.
- FastAPI application structure.
- REST API design.
- Authentication and authorization.
- Project management.
- Image upload and file storage.
- Generation task management.
- Celery and Redis integration.
- Integration with machine learning modules.
- Result delivery and downloading.
- Validation and error handling.
- Logging and monitoring.
- Security and testing requirements.

The backend must implement the functional requirements defined in `01_product_requirements.md`.

It must provide the API required by the frontend specification in `03_frontend_specification.md`.

This document describes HOW the backend must be implemented and HOW its components must interact.

Exact API request and response schemas should be documented centrally in `architecture/api_contracts.md`.

---

## 2. Technology Stack

### 2.1. Core Technologies

| Area | Technology |
|---|---|
| Programming Language | Python |
| Web Framework | FastAPI |
| Data Validation | Pydantic |
| ORM | SQLAlchemy 2.x |
| Database | PostgreSQL |
| Database Migrations | Alembic |
| Background Tasks | Celery |
| Message Broker | Redis |
| File Storage | Local Filesystem |
| API Documentation | OpenAPI / Swagger |
| Containerization | Docker |
| Orchestration | Docker Compose |

### 2.2. Supporting Libraries

Use the following libraries where appropriate:

- Uvicorn — ASGI application server.
- python-multipart — multipart file uploads.
- Pillow — image decoding and validation.
- pydantic-settings — environment-based configuration.
- psycopg — PostgreSQL driver.
- pytest — backend testing.
- httpx — API testing.
- structlog or Python logging — structured logging.

Use compatible, stable dependency versions and pin them in the appropriate dependency files.

Avoid unnecessary dependencies.

---

## 3. Backend Architecture

### 3.1. General Architecture

Use a modular layered architecture.

Separate HTTP request handling, business logic, data access, file storage and background processing.

The backend must not directly implement machine learning algorithms inside API route handlers.

Main architectural layers:

1. API Layer — handles HTTP requests and responses.
2. Service Layer — implements application business logic.
3. Repository Layer — encapsulates database operations.
4. Domain Layer — contains domain models and business rules.
5. Storage Layer — handles source image and generated asset storage.
6. Task Layer — schedules and manages background processing.
7. ML Integration Layer — provides interfaces to generation algorithms.

### 3.2. Request Processing Flow

The standard request flow should be:

```text
Frontend
   |
   v
FastAPI Router
   |
   v
Dependencies and Validation
   |
   v
Service Layer
   |
   +-------------------+
   |                   |
   v                   v
Repository Layer    Storage Layer
   |                   |
   v                   v
PostgreSQL          File Storage
```

Long-running operations use a separate flow:

```text
Frontend
   |
   v
FastAPI
   |
   v
Generation Service
       |
       v
PostgreSQL Transaction
       |
       +---- GenerationTask
       |
       +---- GenerationTaskImage
       |
       +---- Project Status
       |
       +---- OutboxMessage
                 |
                 v
          PostgreSQL Commit
                 |
                 v
         Outbox Dispatcher
                 |
                 v
               Redis
                 |
                 v
             Celery Worker
                 |
                 V
               Celery
                 |
                 v
              Redis
                 |
                 v
              ML Worker
                 |
                 +-----------> TripoSR
                 |
                 +-----------> COLMAP + OpenMVS
                 |
                 v
              Generated Asset
                 |
                 v
              File Storage
                 |
                 v
              PostgreSQL Result Metadata
```

The frontend must never communicate directly with Celery, Redis, PostgreSQL or ML workers.

All communication between the frontend and backend must happen through the REST API.

### 3.3. Separation of Responsibilities

Outbox Dispatcher is responsible for:

- Retrieving pending outbox messages from PostgreSQL.
- Safely claiming messages.
- Publishing messages to Redis.
- Marking successfully published messages.
- Retrying temporary publishing failures.
- Recovering expired message-processing leases.

The dispatcher must support at-least-once message publication.

The FastAPI application is responsible for:

- Authentication.
- Authorization.
- Project management.
- Image upload.
- Image validation.
- File storage coordination.
- Generation task creation.
- Task status retrieval.
- Result metadata.
- Download authorization.
- Application-level error handling.

ML workers are responsible for:

- Loading generation models.
- Executing TripoSR.
- Running COLMAP.
- Running OpenMVS.
- Converting generated assets.
- Saving intermediate processing results.
- Reporting processing progress.
- Reporting success or failure.

The API server must remain independent of heavy ML dependencies wherever possible.

---

## 4. Proposed Backend Directory Structure

Use the following modular structure:

```text
backend/
│
├── app/
│   │
│   ├── main.py
│   │
│   ├── api/
│   │   ├── dependencies.py
│   │   │
│   │   └── v1/
│   │       ├── router.py
│   │       │
│   │       └── endpoints/
│   │           ├── auth.py
│   │           ├── projects.py
│   │           ├── images.py
│   │           ├── generation.py
│   │           └── results.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── logging.py
│   │   ├── exceptions.py
│   │   └── constants.py
│   │
│   ├── db/
│   │   ├── base.py
│   │   ├── session.py
│   │   └── models/
│   │       ├── user.py
│   │       ├── user_session.py
│   │       ├── project.py
│   │       ├── project_image.py
│   │       ├── generation_task.py
│   │       └── generation_result.py
│   │
│   ├── schemas/
│   │   ├── auth.py
│   │   ├── user.py
│   │   ├── project.py
│   │   ├── image.py
│   │   ├── generation.py
│   │   ├── result.py
│   │   └── common.py
│   │
│   ├── repositories/
│   │   ├── user_repository.py
│   │   ├── session_repository.py
│   │   ├── project_repository.py
│   │   ├── image_repository.py
│   │   ├── task_repository.py
│   │   ├── outbox_repository.py
│   │   └── result_repository.py
│   │
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── project_service.py
│   │   ├── image_service.py
│   │   ├── generation_service.py
│   │   ├── task_status_service.py
│   │   ├── outbox_service.py
│   │   └── result_service.py
│   │
│   ├── storage/
│   │   ├── base.py
│   │   ├── local_storage.py
│   │   └── storage_service.py
│   │
│   ├── tasks/
│   │   ├── celery_app.py
│   │   ├── object_tasks.py
│   │   ├── scene_tasks.py
│   │   ├── outbox_dispatcher.py
│   │   ├── task_recovery.py
│   │   └── cleanup_tasks.py
│   │
│   └── ml/
│       ├── interfaces.py
│       ├── registry.py
│       └── adapters/
│           ├── object_generator.py
│           └── scene_reconstructor.py
│
├── alembic/
│   ├── versions/
│   └── env.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── api/
│
├── scripts/
│
├── .env.example
├── alembic.ini
├── requirements.txt
├── Dockerfile
└── README.md
```

The actual ML implementation and its heavy dependencies should be located in the separate `ml/` project directory or in worker-specific packages.

The backend `app/ml/` directory must contain only lightweight interfaces and integration adapters.

Do not import PyTorch or initialize TripoSR inside the FastAPI application.

---

## 5. Application Initialization

### 5.1. FastAPI Application

Initialize the FastAPI application in:

`app/main.py`

The application must configure:

- API routers.
- CORS.
- Authentication dependencies.
- Exception handlers.
- Logging.
- Application lifecycle management.
- Health-check endpoints.

Use the application lifespan mechanism for initialization and resource cleanup where necessary.

Do not execute database migrations automatically during every application startup.

### 5.2. API Versioning

All application endpoints must use the `/api/v1/` prefix.

Example:

```text
/api/v1/projects
/api/v1/auth/login
/api/v1/projects/{project_id}/generate
```

API versioning must allow future changes without breaking existing clients.

### 5.3. OpenAPI Documentation

Use FastAPI's built-in OpenAPI generation.

Provide:

- Swagger UI.
- Request and response schemas.
- Authentication descriptions.
- Endpoint descriptions.
- HTTP response codes.

Swagger UI should be available in development.

Production exposure must be configurable.

---

## 6. Configuration Management

Use `pydantic-settings` to load application settings from environment variables.

Do not hardcode secrets, database credentials or environment-specific paths.

### 6.1. Required Configuration

Example `.env.example`:

```env
APP_ENV=development
APP_NAME=3D Generation Service
DEBUG=true

API_V1_PREFIX=/api/v1

DATABASE_URL=postgresql+psycopg://app:app@db:5432/app

REDIS_URL=redis://redis:6379/0

CELERY_BROKER_URL=redis://redis:6379/1
CELERY_TASK_IGNORE_RESULT=true

STORAGE_ROOT=/data

MAX_UPLOAD_SIZE_MB=20
MAX_SCENE_IMAGES=100
MIN_SCENE_IMAGES=3

SESSION_TTL_HOURS=24

CORS_ORIGINS=http://localhost:5173
```

These values are initial development defaults, not universal technical limits.

The limits must be configurable.

Production secrets must be supplied through a secure environment or secrets management mechanism.

### 6.2. Settings Validation

The application must validate required configuration during startup.

If essential configuration is missing or invalid, the application must fail with an informative server-side error.

Do not expose configuration secrets in logs or API responses.

---

## 7. Database Integration

### 7.1. Database

Use PostgreSQL as the primary persistent data store.

Use SQLAlchemy 2.x for database access.

Use Alembic for database migrations.

The database must store metadata rather than large binary image or 3D model files.

### 7.2. Database Entities

The backend must support the following logical entities:

**User**

Stores user account information.

**UserSession**

Stores authenticated session information and session expiration.

**Project**

Stores project metadata, owner, generation type and current status.

**ProjectImage**

Stores metadata about uploaded source photographs.

**GenerationTask**

Stores processing task information, status and execution details.

**GenerationResult**

Stores metadata and storage references for generated assets.

Detailed fields, types, relationships, constraints and indexes are defined in:

`05_database_specification.md`

### 7.3. Database Access

Use a centralized SQLAlchemy session configuration.

Provide database sessions through FastAPI dependencies.

All operations that modify related entities must use appropriate database transactions.

Use eager loading or optimized queries when necessary to avoid excessive database requests.

### 7.4. Migrations

All database schema changes must be implemented through Alembic migrations.

Do not modify production database schemas manually.

Do not rely on `Base.metadata.create_all()` as the production migration mechanism.

---

## 8. Authentication and Authorization

### 8.1. Authentication Model

Use cookie-based session authentication for the MVP.

The backend should issue an opaque, cryptographically random session token and store only its secure hash in PostgreSQL.

The raw session token must be delivered through an HttpOnly cookie.

The browser must not have access to the session token through JavaScript.

### 8.2. Registration

Endpoint:

`POST /api/v1/auth/register`

The backend must:

1. Validate the submitted email.
2. Validate password requirements.
3. Check whether the account already exists.
4. Hash the password using Argon2id or another modern password hashing algorithm.
5. Create a user record.
6. Return the newly created user information.

Passwords must never be stored in plaintext.

### 8.3. Login

Endpoint:

`POST /api/v1/auth/login`

The backend must:

1. Validate the supplied credentials.
2. Find the corresponding user.
3. Verify the password hash.
4. Generate a cryptographically secure session token.
5. Store the token hash and session expiration.
6. Set the session cookie.
7. Return user information.

Invalid credentials must produce a generic authentication error.

Do not disclose whether a particular email address is registered.

### 8.4. Session Cookie

Use the following cookie properties:

- HttpOnly: enabled.
- Secure: enabled in production.
- SameSite: Lax by default.
- Path: `/`.
- Expiration: configurable.

For local development, Secure may be disabled when using plain HTTP.

Production must use HTTPS.

Configure the frontend and backend on compatible same-site origins when possible.

### 8.5. CSRF Protection

The session cookie must remain HttpOnly.

The CSRF token must be stored in a separate non-HttpOnly cookie
so that the frontend can read it and copy it into the
X-CSRF-Token request header.

The backend must:

- Generate a cryptographically secure CSRF nonce.
- Sign the CSRF token using a server-side secret.
- Bind token validation to the authenticated session.
- Set the CSRF cookie with Secure in production and SameSite=Lax.
- Validate that the request header matches the CSRF cookie.
- Verify the token signature and session binding.
- Validate the Origin header for state-changing requests.

The CSRF token is not an authentication credential.

GET /api/v1/auth/csrf must return the current valid token,
creating and setting a new token only when necessary.

Rotation:

- A new CSRF token is issued when a session is created, which means on successful login and on registration that establishes a session.
- A new CSRF token is issued when a session identifier is regenerated after authentication.
- Rotation invalidates the previous token for that session. A request carrying a rotated-out token must fail with `CSRF_VALIDATION_FAILED`.
- The token is bound to the session, so it has the same lifetime as the session. Logout clears it; session expiration invalidates it.
- Logout must clear both session and CSRF cookies.

### 8.6. Current User

Endpoint:

`GET /api/v1/auth/me`

Return authenticated user information.

If the session is invalid or expired, return HTTP 401.

### 8.7. Logout

Endpoint:

`POST /api/v1/auth/logout`

The backend must:

1. Identify the current session.
2. Revoke the session.
3. Remove the session cookie.
4. Return a successful response.

### 8.8. Authorization

Every protected endpoint must verify the authenticated user.

Project-related operations must validate project ownership.

A user must never be able to access another user's projects, uploaded images, tasks or generated models by changing an identifier in the request.

Return HTTP 404 for inaccessible project resources where appropriate to avoid disclosing their existence.

---

## 9. Project Management

### 9.1. Project Creation

Endpoint:

`POST /api/v1/projects`

The request must contain:

- Project name.
- Project type.

Supported project types:

```text
OBJECT
SCENE
```

The backend must:

1. Authenticate the user.
2. Validate the request.
3. Create a project with a unique identifier.
4. Associate the project with the authenticated user.
5. Set the initial status to CREATED.
6. Store creation metadata.
7. Return the created project.

Project creation must not automatically trigger generation.

### 9.2. Project List

Endpoint:

`GET /api/v1/projects`

Return projects belonging to the authenticated user.

Support:

- Pagination.
- Filtering by project type.
- Filtering by project status.
- Stable sorting by creation date.

Suggested query parameters:

```text
?limit=20&offset=0
&type=OBJECT
&status=COMPLETED
```

Use configurable pagination limits.

### 9.3. Project Details

Endpoint:

`GET /api/v1/projects/{project_id}`

Return:

- Project metadata.
- Generation type.
- Creation date.
- Current status.
- Source image count.
- Result availability.
- Latest generation task information where appropriate.

### 9.4. Project Deletion

Endpoint:

`DELETE /api/v1/projects/{project_id}`

The backend must:

1. Authenticate the user.
2. Verify project ownership.
3. Prevent deletion while an active task is using project resources, or safely cancel and clean up the task first.
4. Remove project metadata.
5. Trigger cleanup of associated images and generated assets.
6. Return a successful deletion response.

Deletion must not leave permanently inaccessible orphaned files.

Implement safe cleanup procedures for cases where database and filesystem operations cannot be completed atomically.

### 9.5. Project State Validation

The backend must enforce valid project lifecycle transitions.

A project must not enter generation processing if required source images are missing.

The project must not start multiple simultaneous generation tasks.

---

## 10. Image Upload and File Storage

### 10.1. Supported Formats

Accept:

- JPEG.
- JPG.
- PNG.

Do not accept arbitrary file formats.

### 10.2. Image Upload Endpoint

Endpoint:

`POST /api/v1/projects/{project_id}/images`

Use multipart/form-data.

Each request should upload one image.

The frontend can submit multiple requests for Scene Reconstruction projects.

This approach supports independent upload progress, failure handling and retries for individual images.

### 10.3. Upload Processing

For each uploaded photograph, the backend must:

1. Authenticate the user.
2. Verify project ownership.
3. Check the project type and current status.
4. Validate file extension.
5. Validate the declared MIME type.
6. Verify the actual file format.
7. Decode the image to ensure that it is valid.
8. Check file size and image dimensions.
9. Generate a unique storage filename.
10. Save the file in the configured storage.
11. Create a ProjectImage database record.
12. Return image metadata.

The backend must not trust user-provided filenames.

Store the original filename as metadata only.

### 10.4. Object Generation Restrictions

For OBJECT projects:

- Exactly one source photograph is allowed.
- Additional photographs must be rejected unless the existing image is removed or replaced.
- The image must be uploaded before generation starts.

### 10.5. Scene Reconstruction Restrictions

For SCENE projects:

- Multiple photographs are allowed.
- The minimum number of photographs is configurable.
- The maximum number of photographs is configurable.
- Every image must pass validation.

Initial development defaults:

- Minimum: 3 images.
- Maximum: 100 images.

Passing these checks does not guarantee that the photographs are suitable for photogrammetric reconstruction.

### 10.6. Upload State

During each image upload:

1. Lock or otherwise safely coordinate access to the project.
2. Verify that no generation task is currently using its images.
3. Set project status to UPLOADING.
4. Perform validation and storage operations.
5. Persist image metadata.
6. Return project status to CREATED after successful upload.
7. Restore a consistent project state after upload failure.

Uploads within one project must be serialized.

The project must not become available for generation until
the current upload operation has completed.

### 10.7. Image Storage

Use a storage abstraction.

The initial implementation must use the local filesystem.

Recommended directory structure:

```text
/data/
│
├── projects/
│   └── {project_id}/
│       ├── source/
│       │   ├── {image_id}.jpg
│       │   └── {image_id}.png
│       │
│       ├── working/
│       │   ├── object/
│       │   └── scene/
│       │
│       └── results/
│           └── model.glb
│
└── temporary/
```

The exact physical storage structure may be adjusted during implementation.

Requirements:

- Keep files outside the publicly served web root.
- Use unpredictable filenames.
- Store paths as metadata.
- Restrict filesystem access.
- Prevent directory traversal.
- Use Docker Volumes for persistent storage.
- Do not expose filesystem paths to frontend clients.

### 10.8. Image Retrieval

Endpoint:

`GET /api/v1/projects/{project_id}/images`

Return image metadata.

Actual file delivery, when required, must use an authorized endpoint or another controlled delivery mechanism.

### 10.9. Image Deletion

Endpoint:

`DELETE /api/v1/projects/{project_id}/images/{image_id}`

Allow deletion only before generation starts or when the project is in a state where source modification is permitted.

Remove the database record and associated file.

Do not allow source images to be modified while a worker is processing them.

### 10.10. File Storage Abstraction

Create a storage interface.

Suggested methods:

```python
class StorageBackend:
    def save(self, source, destination):
        ...

    def delete(self, path):
        ...

    def exists(self, path):
        ...

    def open(self, path):
        ...

    def get_size(self, path):
        ...
```

Implement `LocalStorage` for the MVP.

The abstraction should allow future migration to S3-compatible object storage without changing business services.

---

## 11. Generation Task Management

### 11.1. General Requirements

Generation and reconstruction are computationally expensive operations.

They must be executed asynchronously using Celery workers.

HTTP handlers must only initiate tasks and return task information.

### 11.2. Generation Endpoint

Endpoint:

`POST /api/v1/projects/{project_id}/generate`

The backend must:

1. Authenticate the user.
2. Retrieve the project.
3. Verify project ownership.
4. Validate project state.
5. Verify the required source photographs.
6. Determine the generation type.
7. Create a GenerationTask record.
8. Set project status to PENDING.
9. The generation endpoint must not publish messages to Redis directly.
10. After commit, the Outbox Dispatcher publishes the task.
11. The endpoint returns HTTP 202 Accepted after successful
    database transaction completion.

It must create GenerationTask, GenerationTaskImage references,
update the project status and insert an OutboxMessage
within one PostgreSQL transaction.

Generation requests must include a mandatory, project-scoped `Idempotency-Key`.

The backend stores a `request_fingerprint` derived from the normalized request.

The same key with the same fingerprint returns the existing task.

The same key with a different fingerprint returns HTTP 409.

A new user-initiated generation attempt must use a new key.

Internal worker recovery reuses the existing GenerationTask.

Scene Reconstruction must enqueue a scene-reconstruction task.

### 11.3. Task Status

The task must support the following states:

```text
PENDING
PROCESSING
COMPLETED
FAILED
CANCELLED
```

`CANCELLED` is an internal terminal state used when processing must be stopped, primarily during project deletion.

Project lifecycle states:

```text
CREATED
UPLOADING
PENDING
PROCESSING
COMPLETED
FAILED
```

UPLOADING is a transient project state during image transfer.

Generation task states and project states must be kept consistent.

### 11.4. Task Status Endpoint

Endpoint:

`GET /api/v1/projects/{project_id}/status`

Return:

- Project status.
- Latest task identifier.
- Task status.
- Current processing stage.
- Progress percentage, if reliably available.
- User-friendly status message.
- Error code and message when processing fails.
- Task creation and completion timestamps.

Do not fabricate processing progress.

### 11.5. Task Execution

Celery tasks must receive identifiers rather than large image payloads.

The worker retrieves source image paths and task metadata through shared storage and the database.

Recommended execution flow:

```text
API Request
    |
    v
Generation Service
    |
    v
Create GenerationTask
    |
    v
Update Project Status
    |
    v
Enqueue Celery Message
    |
    v
Redis
    |
    v
Worker
    |
    v
Execute ML Pipeline
    |
    v
Save Result
    |
    v
Update Task Status
    |
    v
Update Project Status
```

### 11.6. Task Queues

Use separate queues for different workloads:

```text
object_generation
scene_reconstruction
file_cleanup
```

This separation allows independent worker configuration.

Scene reconstruction must not block object generation tasks unnecessarily.

### 11.7. Worker Isolation

Use dedicated worker processes or containers where practical.

Recommended logical services:

- Object Worker — executes TripoSR.
- Scene Worker — executes COLMAP and OpenMVS.
- Cleanup Worker — performs file cleanup operations.

The two ML worker types should have independent dependency environments.

Do not require the API container to install PyTorch, TripoSR, COLMAP or OpenMVS.

### 11.8. Duplicate Task Protection

The backend must prevent multiple active generation tasks for one project.

Before task creation:

- Check the project state.
- Check for active tasks.
- Use a database transaction.
- Enforce the active-task constraint at the persistence layer where practical.

The Idempotency-Key header is mandatory for generation initiation.

The key must be scoped to a project.

Repeating the same request with the same key must return
the existing GenerationTask.

A new manual generation attempt must use a new key.

Reusing an existing key with a different request fingerprint
must return HTTP 409 Conflict.


### 11.9. Task Retry

A failed generation task may be retried.

Retry behavior:

1. Verify that the previous task reached FAILED.
2. Verify source photographs still exist.
3. Create a new task record.
4. Set project status to PENDING.
5. Enqueue a new background operation.

Retain previous task records for debugging and generation history.

Do not automatically repeat deterministic processing failures indefinitely.

Automatic retries should be limited to recoverable infrastructure errors.

### 11.10. Worker Failure Recovery

The system should handle:

- Unexpected worker termination.
- Redis connection interruptions.
- Task execution timeouts.
- GPU out-of-memory errors.
- Missing source files.
- Missing generated outputs.
- Database connectivity failures.

Celery task delivery may be repeated.

Therefore, task execution must be designed to be idempotent.

A repeated worker execution must not create multiple conflicting project results.

Implement a persistent task recovery mechanism.

Every active worker task must maintain a heartbeat and lease.

A recovery process must periodically inspect tasks in PROCESSING.

If a task lease expires:

- Determine whether its worker is still active.
- Inspect task execution state.
- Requeue the task when safe and retry limits permit.
- Otherwise mark the task FAILED.
- Create a new outbox event for re-dispatch when necessary.

Do not automatically create a new user-visible GenerationTask
for an internal worker recovery attempt.

Manual retries must create separate GenerationTask records.

### 11.11. Task Progress

Workers should report meaningful processing stages.

For object generation:

- IMAGE_PREPARATION.
- MODEL_GENERATION.
- MODEL_EXPORT.
- RESULT_VALIDATION.

For scene reconstruction:

- IMAGE_PREPARATION.
- FEATURE_EXTRACTION.
- FEATURE_MATCHING.
- SPARSE_RECONSTRUCTION.
- RECONSTRUCTION_VALIDATION.
- IMAGE_UNDISTORTION.
- OPENMVS_IMPORT.
- DENSE_RECONSTRUCTION.
- MESH_GENERATION.
- MESH_REFINEMENT.
- TEXTURING.
- ASSET_EXPORT.
- RESULT_VALIDATION.

Progress percentages should only be reported when actual progress can be calculated.

The API must return the latest persisted task information.

PostgreSQL is the source of truth for task status.

Redis must not be the only place where task state is stored.

---

## 12. Machine Learning Integration

### 12.1. General Architecture

The backend must isolate ML implementations behind well-defined interfaces.

The business logic must not depend directly on TripoSR, COLMAP or OpenMVS internal APIs.

Use separate generation interfaces.

### 12.2. Object Generation Interface

Define an object generation interface.

Example:

```python
from abc import ABC, abstractmethod
from pathlib import Path

class ObjectGenerator(ABC):

    @abstractmethod
    def generate(
        self,
        input_image: Path,
        output_dir: Path
    ) -> Path:
        pass
```

The actual implementation must be provided by the Object Worker.

Implement:

`TripoSRGenerator`

Responsibilities:

- Load the TripoSR model.
- Prepare the input image.
- Execute inference.
- Generate mesh geometry.
- Apply required post-processing.
- Export the generated model.
- Return the output artifact.

Do not load the ML model for every individual request if it can remain initialized within the worker process.

Manage GPU memory carefully.

### 12.3. Scene Reconstruction Interface

Define a scene reconstruction interface.

Example:

```python
class SceneReconstructor(ABC):

    @abstractmethod
    def reconstruct(
        self,
        input_images: list[Path],
        output_dir: Path
    ) -> Path:
        pass
```

Implement:

`PhotogrammetryReconstructor`

Responsibilities:

- Prepare image collection.
- Run COLMAP feature extraction.
- Run feature matching.
- Estimate camera positions.
- Generate sparse reconstruction.
- Execute dense reconstruction.
- Integrate OpenMVS.
- Generate mesh geometry.
- Generate textures.
- Convert the final result to GLB.
- Validate the exported asset.

The actual processing pipeline is described in:

`07_scene_reconstruction.md`.

### 12.4. ML Adapter Layer

The backend should communicate with ML processing through task interfaces.

Avoid importing algorithm-specific dependencies into general service classes.

The service layer should only select the correct generation implementation and schedule execution.

### 12.5. Processing Results

Every successful generation task must produce:

- A valid output file.
- A known output format.
- A recorded file size.
- A project association.
- A task association.

Do not mark a task COMPLETED before confirming that the output file exists and passes basic validation.

### 12.6. Output Validation

Before saving a generation result:

- Verify the file exists.
- Verify the file is not empty.
- Verify the file format.
- Verify that the asset can be parsed.
- Record its size.
- Move it to the final storage location.

For GLB, perform at least basic container and glTF structure validation.

If validation fails, mark the task FAILED.

---

## 13. Result Management and Download

### 13.1. Result Retrieval

Endpoint:

`GET /api/v1/projects/{project_id}/result`

Return generation result metadata.

The response should include:

- Result identifier.
- Project identifier.
- File format.
- File size.
- Creation timestamp.
- Availability status.

Do not return internal filesystem paths.

### 13.2. Result Download

Endpoint:

`GET /api/v1/projects/{project_id}/download`

Requirements:

- Authenticate the user.
- Verify project ownership.
- Verify result availability.
- Verify the generated file exists.
- Return the GLB file as a download response.
- Set an appropriate Content-Type.
- Set a safe Content-Disposition filename.

Recommended MIME type:

`model/gltf-binary`

Use streaming file responses when appropriate.

Do not load large model files entirely into application memory.

### 13.3. Download Security

Only authorized users must be able to download a project's results.

Do not create permanent public download URLs for private assets.

The application must not expose internal storage paths.

### 13.4. Result Replacement

When a generation task is retried and succeeds:

- Store the new result.
- Update the project's current result reference.
- Preserve previous task metadata.
- Clean up obsolete assets according to the retention policy.

Do not delete a previous valid result before the new result has been successfully validated and saved.

---

## 14. API Endpoint Summary

The API must provide the following endpoint groups.

### 14.1. Authentication

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/auth/register` | Register a user |
| POST | `/api/v1/auth/login` | Authenticate |
| POST | `/api/v1/auth/logout` | Terminate session |
| GET | `/api/v1/auth/me` | Get current user |
| GET | `/api/v1/auth/csrf` | Obtain CSRF token |

### 14.2. Projects

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/projects` | Create project |
| GET | `/api/v1/projects` | List projects |
| GET | `/api/v1/projects/{id}` | Get project details |
| DELETE | `/api/v1/projects/{id}` | Delete project |

### 14.3. Images

| Method | Endpoint | Purpose            |
|---|---|--------------------|
| POST | `/api/v1/projects/{id}/images` | Upload one image   |
| GET | `/api/v1/projects/{id}/images` | List project images |
| GET | `/api/v1/projects/{project_id}/images/{image_id}/content` | get image          |
| DELETE | `/api/v1/projects/{id}/images/{image_id}` | Delete image       |

### 14.4. Generation

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/projects/{id}/generate` | Start generation |
| GET | `/api/v1/projects/{id}/status` | Get processing status |

### 14.5. Results

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/projects/{id}/result` | Get result metadata |
| GET | `/api/v1/projects/{id}/download` | Download generated asset |

The exact schemas, payload structures, HTTP status codes and error response formats must be maintained in `architecture/api_contracts.md`.

The API contract must be treated as the single source of truth for frontend/backend integration.

---

## 15. API Response and Error Handling

### 15.1. Successful Responses

Use standard HTTP status codes.

Recommended behavior:

| Code | Usage |
|---|---|
| 200 | Successful retrieval or operation |
| 201 | Resource created |
| 202 | Background task accepted |
| 204 | Successful deletion or operation without response body |

### 15.2. Error Responses

Use a consistent error response structure.

Example:

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

All API errors should contain:

- Stable machine-readable error code.
- User-friendly message.
- Optional validation details.
- Request identifier for diagnostics.

Do not return internal stack traces.

### 15.3. Error Categories

Implement centralized handling for:

**Validation Errors**

- Missing required fields.
- Invalid project type.
- Invalid file format.
- File size limit exceeded.
- Invalid image count.

**Authentication Errors**

- Missing session.
- Invalid session.
- Expired session.
- Invalid credentials.

**Authorization Errors**

- Project ownership violation.
- Unauthorized file access.

**Resource Errors**

- Project not found.
- Image not found.
- Result not found.

**Processing Errors**

- Invalid project state.
- Generation already running.
- Missing input files.
- ML processing failure.
- GPU memory failure.
- Reconstruction failure.
- Worker unavailable.

**Infrastructure Errors**

- Database unavailable.
- Redis unavailable.
- Storage unavailable.
- Unexpected internal errors.

### 15.4. Logging and Request Identification

Generate a unique request ID for incoming API requests.

Include it in:

- Application logs.
- Error responses.
- Relevant task logs.

Task identifiers must be logged separately from HTTP request identifiers.

---

## 16. Logging and Monitoring

### 16.1. Logging

Use structured logging.

Logs should contain:

- Timestamp.
- Log level.
- Service name.
- Request identifier.
- User identifier where appropriate.
- Project identifier.
- Generation task identifier.
- Operation name.
- Error information.

Avoid logging passwords, raw session tokens, CSRF tokens or sensitive file contents.

### 16.2. Task Logging

Workers must record:

- Task creation.
- Task execution start.
- Processing stages.
- Processing completion.
- Processing failures.
- Retry attempts.

### 16.3. Health Checks

Provide basic health endpoints:

`GET /health/live`

Indicates that the API process is running.

`GET /health/ready`

Checks whether the application can access essential dependencies such as PostgreSQL.

Redis and worker availability may be included in a separate dependency health report.

A temporary ML worker outage should not necessarily make basic project management unavailable.

### 16.4. Monitoring

The MVP should provide sufficient logs to diagnose:

- Failed uploads.
- Failed database operations.
- Failed Celery tasks.
- ML processing errors.
- Storage errors.
- Unexpected worker termination.

Advanced metrics and dashboards are outside the initial MVP scope.

---

## 17. Security Requirements

### 17.1. Input Validation

Validate all incoming requests using Pydantic.

Never trust data received from the frontend.

### 17.2. Password Security

- Hash passwords using Argon2id or an equivalent secure algorithm.
- Never store plaintext passwords.
- Never log passwords.
- Enforce configurable password requirements.

### 17.3. Session Security

- Use cryptographically secure session tokens.
- Store only session token hashes.
- Support session expiration.
- Revoke sessions on logout.
- Protect cookie-authenticated state-changing operations against CSRF.

### 17.4. File Security

- Validate actual file contents.
- Use generated filenames.
- Restrict accepted extensions.
- Enforce file size and image dimension limits.
- Store user files outside publicly accessible directories.
- Prevent path traversal.
- Restrict file access by project ownership.
- Clean up incomplete uploads.

### 17.5. CORS

Configure CORS with explicitly allowed frontend origins.

Allow credentials only for approved origins.

Do not use wildcard origins with credentialed requests.

### 17.6. Resource Protection

Protect the application against:

- Excessively large uploads.
- Excessive image counts.
- Duplicate generation requests.
- Unlimited parallel processing.
- Resource exhaustion.
- Unexpectedly large image dimensions.

Limit worker concurrency according to available CPU and GPU resources.

### 17.7. Worker Isolation

Workers should execute with the minimum required permissions.

Avoid giving ML processes unnecessary access to authentication secrets or unrelated project files.

---

## 18. Background Task Configuration

### 18.1. Celery Configuration

Initialize Celery through a dedicated application module.

Use Redis as the message broker.

Do not configure a separate Celery result backend. Set `CELERY_TASK_IGNORE_RESULT=true`; PostgreSQL remains the authoritative source for generation task status and results.

### 18.2. Task Reliability

Configure Celery for:

- Task acknowledgements after successful processing where appropriate.
- Task time limits.
- Worker-loss handling.
- Bounded retries.
- Task event logging.

Review acknowledgement and visibility-timeout settings together to avoid either losing tasks or allowing unintended duplicate processing.

### 18.3. Task Concurrency

Object generation may require significant GPU memory.

Set conservative worker concurrency.

Scene reconstruction may require significant CPU memory, disk space and processing time.

Configure its workers independently.

Do not assume that increasing the number of workers always improves performance.

### 18.4. Temporary Files

Workers must use isolated temporary working directories for individual tasks.

After successful processing:

- Save the final asset.
- Persist result metadata.
- Remove unnecessary intermediate files according to retention rules.

On failure:

- Preserve useful diagnostic information where appropriate.
- Clean up incomplete outputs.
- Avoid leaving large temporary directories indefinitely.

### 18.5. Task Timeout

Set configurable time limits.

Long-running scene reconstruction tasks must have limits appropriate to the expected image count and hardware.

Timeouts must result in a recoverable FAILED state or another explicitly handled terminal state.

---

## 19. Testing Requirements

Use pytest for automated backend testing.

### 19.1. Unit Tests

Test:

- Authentication service.
- Password hashing and verification.
- Session validation.
- Project business rules.
- Project state transitions.
- Image validation.
- Storage operations.
- Generation task creation.
- Result validation.
- Error mapping.

### 19.2. API Tests

Test:

- Registration.
- Login.
- Logout.
- Current user retrieval.
- Project creation.
- Project listing.
- Project details.
- Project deletion.
- Image uploads.
- Image deletion.
- Generation initiation.
- Task status retrieval.
- Result metadata.
- Result download.

### 19.3. Authorization Tests

Verify that:

- Unauthenticated users cannot access protected endpoints.
- Users cannot access other users' projects.
- Users cannot upload images into other users' projects.
- Users cannot retrieve other users' results.
- Users cannot download unauthorized files.

### 19.4. Image Upload Tests

Verify:

- Valid JPEG uploads.
- Valid PNG uploads.
- Invalid file rejection.
- Oversized file rejection.
- Invalid image content rejection.
- Excessive image count rejection.
- Object project single-image restriction.
- Scene project multi-image support.
- Temporary file cleanup after upload failures.

### 19.5. Task Processing Tests

Use mocked Celery tasks and ML adapters when testing API behavior.

Verify:

- Task creation.
- Correct queue selection.
- Duplicate task protection.
- Project status updates.
- Failed task handling.
- Retry behavior.
- Result metadata persistence.

### 19.6. Integration Tests

Use a test database and isolated storage directory.

Test the integration of:

- FastAPI and PostgreSQL.
- FastAPI and Redis.
- Celery and Redis.
- Celery and PostgreSQL.
- Backend and local storage.

ML model execution should be tested separately from ordinary API integration tests.

---

## 20. Development Order

Implement the backend incrementally.

### Phase 1. Initial Setup

- Initialize FastAPI.
- Configure project dependencies.
- Configure environment settings.
- Configure PostgreSQL.
- Configure SQLAlchemy.
- Configure Alembic.
- Implement health endpoints.

### Phase 2. Database and Domain Models

- Create User.
- Create UserSession.
- Create Project.
- Create ProjectImage.
- Create GenerationTask.
- Create GenerationResult.
- Implement migrations.
- Add repositories.

### Phase 3. Authentication

- Implement registration.
- Implement login.
- Implement session management.
- Implement logout.
- Implement current-user endpoint.
- Implement CSRF protection.
- Implement authorization dependencies.

### Phase 4. Project Management

- Implement project creation.
- Implement project listing.
- Implement pagination and filtering.
- Implement project details.
- Implement project deletion.
- Implement ownership validation.

### Phase 5. Image Upload

- Implement storage abstraction.
- Implement LocalStorage.
- Implement image validation.
- Implement image upload.
- Implement image listing.
- Implement image deletion.
- Implement upload error handling.

### Phase 6. Background Processing

- Configure Celery.
- Configure Redis.
- Create generation task model.
- Implement task creation.
- Implement object and scene queues.
- Implement task status retrieval.
- Implement duplicate task protection.
- Implement task failure handling.

### Phase 7. ML Integration

- Define ObjectGenerator interface.
- Define SceneReconstructor interface.
- Integrate TripoSR adapter.
- Integrate COLMAP/OpenMVS adapter.
- Implement result validation.
- Implement processing status updates.

Detailed algorithm integration is covered by the dedicated ML specifications.

### Phase 8. Result Management

- Implement result metadata.
- Implement GLB validation.
- Implement authorized downloads.
- Implement result replacement.
- Implement cleanup procedures.

### Phase 9. Testing and Stabilization

- Complete unit tests.
- Complete API tests.
- Complete authorization tests.
- Complete integration tests.
- Test failure scenarios.
- Verify Docker Compose integration.
- Document deployment and configuration.

---

## 21. Acceptance Criteria

### BE-AC-01. Application Startup

FastAPI starts successfully and exposes the configured API.

### BE-AC-02. Database Integration

The backend can establish a PostgreSQL connection and apply Alembic migrations.

### BE-AC-03. Registration

A user can create an account with valid credentials.

Passwords are stored as secure hashes.

### BE-AC-04. Authentication

A registered user can log in and obtain an authenticated session.

### BE-AC-05. Session Security

The session cookie uses the required security attributes and session revocation works.

### BE-AC-06. Authorization

Users can only access their own projects and associated resources.

### BE-AC-07. Project Creation

The API supports creation of OBJECT and SCENE projects.

### BE-AC-08. Project Management

Users can list, retrieve and delete their own projects.

### BE-AC-09. Image Upload

The backend accepts valid JPEG and PNG images and stores them persistently.

### BE-AC-10. File Validation

Invalid, unsupported and oversized image files are rejected.

### BE-AC-11. Object Upload Restrictions

OBJECT projects accept exactly one source photograph.

### BE-AC-12. Scene Upload Restrictions

SCENE projects accept multiple source photographs within configured limits.

### BE-AC-13. Task Creation

The generation API creates persistent generation tasks and schedules corresponding background processing.

### BE-AC-14. Queue Separation

Object and scene tasks are routed to their respective processing queues.

### BE-AC-15. Task Status

The API returns accurate task and project statuses.

### BE-AC-16. Duplicate Protection

The backend prevents unintended concurrent generation tasks for a single project.

### BE-AC-17. ML Integration

The backend successfully invokes the corresponding ML worker through the task-processing architecture.

### BE-AC-18. Failure Handling

Failed generation tasks are recorded and exposed through the status API.

### BE-AC-19. Result Management

Successfully generated assets are validated, stored and associated with the corresponding project.

### BE-AC-20. Model Download

An authorized user can download a completed GLB asset.

### BE-AC-21. Storage Persistence

Uploaded images and generated models remain available after application container restarts.

### BE-AC-22. Logging

API requests and background tasks produce useful diagnostic logs.

### BE-AC-23. Testing

The backend passes unit, API, authorization and integration tests.

### BE-AC-24. Docker Integration

The backend and supporting services can run through Docker Compose.

---

## 22. Related Specifications

This document defines backend architecture and implementation requirements.

Related documents:

- `00_project_overview.md` — overall project context.
- `01_product_requirements.md` — functional and non-functional requirements.
- `02_ui_ux_specification.md` — interface requirements.
- `03_frontend_specification.md` — frontend architecture and API consumption.
- `05_database_specification.md` — database entities, relationships and constraints.
- `06_object_generation.md` — TripoSR implementation.
- `07_scene_reconstruction.md` — COLMAP and OpenMVS implementation.
- `08_infrastructure.md` — Docker, Redis, Celery and deployment.
- `09_testing.md` — overall testing strategy.
- `10_development_roadmap.md` — development sequence.
- `architecture/api_contracts.md` — canonical REST API contracts.
- `AI_DEVELOPMENT_GUIDE.md` — development workflow, quality gates and agent rules.

All backend endpoints and services must remain consistent with these specifications.
