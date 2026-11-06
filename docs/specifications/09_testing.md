# 09 — Testing & Quality Specification

## 1. Document Purpose

This document defines the testing strategy and quality assurance requirements for the 3D generation web application.

It describes:

- Testing architecture.
- Testing levels.
- Frontend testing.
- Backend testing.
- Database testing.
- API testing.
- Background task testing.
- ML pipeline testing.
- 3D asset validation.
- End-to-end testing.
- Performance testing.
- Security testing.
- CI/CD quality gates.
- Test environments.
- Acceptance criteria.

The purpose of this specification is to ensure that application functionality, data integrity, processing reliability and generated 3D assets meet the required quality standards.

This document describes HOW the application must be tested and HOW its quality must be evaluated.

---

## 2. Testing Strategy

### 2.1. General Approach

Use a layered testing strategy.

The application must be tested at four primary levels:

1. Unit Testing.
2. Integration Testing.
3. End-to-End Testing.
4. ML Quality and Performance Testing.

Each testing level must have a clearly defined scope.

### 2.2. Testing Levels

| Level | Scope | Technologies |
|---|---|---|
| Unit | Individual functions and components | pytest, Vitest |
| Integration | Interactions between application services | pytest, HTTPX |
| End-to-End | Complete user workflows | Playwright |
| ML Quality | Actual 3D generation and reconstruction | PyTorch, COLMAP, OpenMVS |

### 2.3. Testing Principles

- Test business logic independently of infrastructure where possible.
- Use mocks for expensive or external dependencies in ordinary automated tests.
- Use real PostgreSQL and Redis in integration testing.
- Use actual ML models and reconstruction tools in dedicated integration tests.
- Validate generated assets rather than relying only on process exit codes.
- Test successful and failed execution paths.
- Test authorization and data isolation.
- Preserve reproducible test datasets.
- Avoid destructive operations against development or production data.
- Keep test execution independent from user-uploaded production files.

### 2.4. Test Independence

Every test must be isolated from unrelated tests.

Tests must not depend on execution order.

Each test must have:

- Controlled input data.
- Defined initial state.
- Explicit dependencies.
- Predictable cleanup.
- Clear expected results.

Use temporary directories and isolated databases where appropriate.

---

## 3. Testing Environment

### 3.1. Environment Separation

Maintain separate environments:

**Local Development**

Used for fast development testing.

Includes:
- Frontend tests.
- Backend unit tests.
- Mocked API tests.
- Database logic tests.
- Mocked Celery execution.

**Integration Environment**

Used for testing real service interactions.

Includes:
- FastAPI.
- PostgreSQL.
- Redis.
- Celery.
- Shared file storage.

**ML Testing Environment**

Used for actual inference and reconstruction.

Includes:
- TripoSR.
- PyTorch.
- CUDA when available.
- COLMAP.
- OpenMVS.
- Representative image datasets.

**E2E Environment**

Used for complete application workflows.

Includes:
- Frontend.
- Backend.
- Database.
- Redis.
- Workers.
- Browser automation.

### 3.2. Test Configuration

Use dedicated environment files.

Examples:

```text
.env.example
.env.test
.env.integration
.env.ml-test
```

Never reuse production credentials or production storage directories.

### 3.3. Test Data Isolation

Each test environment must use:

- Dedicated database schemas or databases.
- Temporary file storage.
- Isolated Redis databases or instances.
- Unique test users.
- Unique project identifiers.
- Test-specific model outputs.

Do not allow test cleanup to delete real user assets.

### 3.4. GPU Availability

Ordinary tests must not require a GPU.

Actual TripoSR inference tests should use a configured GPU runner when available.

CPU inference may be used for limited diagnostic tests but should not be assumed to provide representative performance measurements.

Scene reconstruction tests must be executable on CPU for the initial MVP.

---

## 4. Testing Tools

### 4.1. Frontend

| Tool | Purpose |
|---|---|
| Vitest | Unit testing |
| React Testing Library | React component testing |
| Playwright | Browser E2E testing |
| MSW | API mocking |
| TypeScript | Static type checking |
| ESLint | Code quality |

### 4.2. Backend

| Tool | Purpose |
|---|---|
| pytest | Main testing framework |
| HTTPX | HTTP client testing |
| FastAPI TestClient | API testing |
| pytest-cov | Code coverage |
| pytest-mock | Mocking |
| Testcontainers | Isolated infrastructure testing |
| Alembic | Migration verification |

### 4.3. ML Processing

| Tool | Purpose |
|---|---|
| pytest | ML unit and integration tests |
| PyTorch | Model execution tests |
| Pillow | Image validation |
| Trimesh | Mesh inspection |
| PyGLM or compatible glTF tooling | Geometry and asset inspection |
| glTF Validator | glTF/GLB structural validation |
| COLMAP | Photogrammetry integration tests |
| OpenMVS | Dense reconstruction tests |

Select specific library versions compatible with the pinned ML environments.

### 4.4. Infrastructure

Use:

- Docker.
- Docker Compose.
- Docker health checks.
- Shell-based environment verification.
- PostgreSQL backup and restore utilities.

---

## 5. Test Organization

### 5.1. General Repository Structure

Organize tests alongside the corresponding application modules or in dedicated test directories.

Suggested structure:

```text
project/
│
├── frontend/
│   └── src/
│       └── ...
│
├── backend/
│   ├── app/
│   │   └── ...
│   │
│   └── tests/
│       ├── conftest.py
│       │
│       ├── unit/
│       │   ├── test_auth_service.py
│       │   ├── test_project_service.py
│       │   ├── test_image_service.py
│       │   ├── test_generation_service.py
│       │   └── test_storage_service.py
│       │
│       ├── api/
│       │   ├── test_auth_api.py
│       │   ├── test_projects_api.py
│       │   ├── test_images_api.py
│       │   ├── test_generation_api.py
│       │   └── test_results_api.py
│       │
│       ├── integration/
│       │   ├── test_database.py
│       │   ├── test_storage.py
│       │   ├── test_celery.py
│       │   └── test_outbox.py
│       │
│       └── fixtures/
│
├── ml/
│   ├── object_generation/
│   │   └── tests/
│   │       ├── test_preprocessing.py
│   │       ├── test_mesh.py
│   │       ├── test_export.py
│   │       └── test_inference.py
│   │
│   ├── scene_reconstruction/
│   │   └── tests/
│   │       ├── test_dataset.py
│   │       ├── test_colmap.py
│   │       ├── test_openmvs.py
│   │       ├── test_pipeline.py
│   │       └── test_export.py
│   │
│   └── tests/
│       ├── fixtures/
│       ├── datasets/
│       └── test_glb_validation.py
│
├── e2e/
│   ├── tests/
│   │   ├── auth.spec.ts
│   │   ├── projects.spec.ts
│   │   ├── object-generation.spec.ts
│   │   ├── scene-reconstruction.spec.ts
│   │   └── model-viewer.spec.ts
│   │
│   └── playwright.config.ts
│
└── infrastructure/
    └── tests/
        ├── test_compose.sh
        ├── test_health.sh
        └── test_persistence.sh
```

The exact directory organization may be adjusted to the final repository structure.

### 5.2. Test Naming

Use descriptive test names.

Examples:

```text
test_create_project_success
test_create_project_without_authentication
test_upload_invalid_image_format
test_prevent_duplicate_generation
test_failed_generation_preserves_previous_result
test_export_valid_glb
```

Test names must describe the behavior being verified.

### 5.3. Test Markers

Use pytest markers to distinguish execution groups.

Recommended markers:

```python
import pytest

@pytest.mark.unit
@pytest.mark.integration
@pytest.mark.api
@pytest.mark.ml
@pytest.mark.gpu
@pytest.mark.slow
@pytest.mark.e2e
```

Register custom markers in pytest configuration.

The test runner must be able to execute individual groups without running the entire suite.

---

## 6. Frontend Testing

### 6.1. Unit Testing

Use Vitest to test independent frontend logic.

Required areas:

**Project Logic**

- Project status mapping.
- Project type mapping.
- Project data formatting.
- Project filtering.
- Project date formatting.

**Image Upload**

- Supported format validation.
- File size validation.
- Image count validation.
- Image removal.
- Preview URL management.
- Invalid file handling.

**Generation UI**

- Generation mode selection.
- Button availability.
- Processing state mapping.
- Error message mapping.
- Task status transitions.

**Model Viewer**

- Viewer configuration.
- Asset URL handling.
- Loading state.
- Error state.
- Camera control state.

### 6.2. Component Testing

Use React Testing Library.

Test:

- Registration form.
- Login form.
- Project card.
- Project status badge.
- Project grid.
- Empty project state.
- Generation mode card.
- ImageDropzone.
- Image preview.
- Processing indicator.
- Generation error.
- Download button.
- Viewer toolbar.

Verify component behavior rather than relying exclusively on implementation-specific details.

### 6.3. API Mocking

Use MSW or an equivalent mocking mechanism for frontend tests.

Mock API responses for:

- Authentication.
- Project retrieval.
- Project creation.
- Image uploading.
- Generation initiation.
- Task status retrieval.
- Result retrieval.
- Result downloads.

Do not require a running ML pipeline for ordinary frontend component tests.

### 6.4. Authentication Tests

Verify:

- Login success.
- Login failure.
- Registration success.
- Registration validation.
- Session initialization.
- Logout.
- Redirect from protected pages.
- Handling of expired sessions.

### 6.5. Image Upload Tests

Verify:

- Single-image mode.
- Multiple-image mode.
- JPEG upload.
- PNG upload.
- Invalid extension.
- Invalid actual image content.
- Oversized file.
- Duplicate image handling.
- Removing uploaded images.
- Upload failure.
- Failed upload retry.
- Temporary object URL cleanup.

### 6.6. Generation State Tests

Verify all supported states:

- CREATED.
- UPLOADING.
- PENDING.
- PROCESSING.
- COMPLETED.
- FAILED.

Check that the UI displays the correct actions for each state.

For example:

- CREATED: generation can be started when inputs are valid.
- PENDING: generation action is disabled.
- PROCESSING: processing information is displayed.
- COMPLETED: result viewer and download are available.
- FAILED: error information and retry action are displayed when permitted.

### 6.7. Three.js Component Tests

Use lightweight GLB fixtures.

Verify:

- Viewer initialization.
- Asset loading.
- Loading indicator.
- Invalid GLB handling.
- Model visibility.
- Camera reset.
- Fit to View.
- Resource disposal.
- Switching between different models.

Use mocked WebGL functionality when full browser rendering is not required.

---

## 7. Backend Testing

### 7.1. Unit Testing

Use pytest for backend unit testing.

Test each service independently.

Required modules:

- AuthService.
- ProjectService.
- ImageService.
- GenerationService.
- TaskStatusService.
- ResultService.
- StorageService.

### 7.2. Authentication Tests

Verify:

- Password hashing.
- Password verification.
- Session creation.
- Session token validation.
- Session expiration.
- Session revocation.
- Logout.
- CSRF validation.
- Inactive account rejection.

Test that session token hashes are stored instead of raw session tokens.

### 7.3. Project Management Tests

Verify:

- Project creation.
- Project type validation.
- Project name validation.
- Project listing.
- Pagination.
- Filtering.
- Project retrieval.
- Project deletion.
- Project ownership validation.
- Soft deletion behavior.

### 7.4. Image Management Tests

Test:

- JPEG validation.
- PNG validation.
- MIME type validation.
- Actual image decoding.
- Invalid file rejection.
- File size restriction.
- Image dimension restriction.
- Unique filename generation.
- Storage persistence.
- Checksum generation.
- Object single-image restriction.
- Scene multi-image restriction.
- Image deletion.
- Incomplete upload cleanup.

### 7.5. Generation Service Tests

Verify:

- Object task creation.
- Scene task creation.
- Correct task type selection.
- Task-to-project association.
- Source image snapshot creation.
- Project status transitions.
- Duplicate task prevention.
- Idempotency handling.
- Request idempotency key validation.
- Request fingerprint validation.
- Atomic worker task claiming.
- Worker lease expiration.
- Internal task cancellation.
- Recovery of interrupted tasks.
- Retry behavior.
- Task error persistence.
- Result registration.

### 7.6. Previous Result Preservation

This behavior must have dedicated regression tests.

Scenario:

1. Create a project.
2. Generate a valid model.
3. Mark the result as current.
4. Start another generation task.
5. Simulate generation failure.
6. Verify the previous result remains available.
7. Verify the previous result is still current.

Also test successful regeneration:

1. Create a previous successful result.
2. Start a new generation.
3. Complete the new generation successfully.
4. Verify the new result becomes current.
5. Verify historical result metadata is preserved.

### 7.7. API Testing

Use FastAPI TestClient or HTTPX.

Test:

- HTTP status codes.
- Response structures.
- Request validation.
- Authentication cookies.
- CSRF behavior.
- Authorization.
- Error response consistency.
- File upload responses.
- Download responses.

API tests must verify the documented API contract.

### 7.8. Dependency Overrides

Use FastAPI dependency overrides to replace expensive or external services during isolated API tests.

Examples:

- Replace the database dependency with a test database session.
- Replace authentication dependencies with controlled test users.
- Replace storage implementations with temporary storage.
- Replace generation task submission with a test dispatcher.

Reset overrides after each relevant test.

Do not allow test-specific overrides to leak into other tests.

---

## 8. Database Testing

### 8.1. Database Initialization

Test the initial database schema using Alembic migrations.

Verify that all expected tables, indexes and constraints are present.

### 8.2. Entity Tests

Test all database entities:

- User.
- UserSession.
- Project.
- ProjectImage.
- GenerationTask.
- GenerationTaskImage.
- GenerationResult.
- StorageCleanupJob.
- OutboxMessage.

The `OutboxMessage` entity is part of the Transactional Outbox schema and must be tested like every other entity.

### 8.3. Constraint Tests

Verify:

- Unique user email.
- Unique session token hash.
- Valid project types.
- Valid project statuses.
- Valid task statuses.
- Valid image file sizes.
- Unique storage keys.
- Unique Celery task identifiers.
- Unique generation task result association.
- Unique project-scoped idempotency key.
- Composite task-image project ownership constraints.
- Composite generation result project-task ownership constraints.
- Valid OutboxMessage states.
- Valid worker lease information.
- Maximum one active generation task per project.
- Maximum one current generation result per project.
- Valid foreign key relationships.

### 8.4. Transaction Tests

Verify:

- Successful project transactions.
- Transaction rollback.
- Image upload rollback.
- Generation task creation.
- Generation task and image snapshot consistency.
- Result registration.
- Previous result replacement.
- Cleanup job persistence.

### 8.5. Concurrent Access Tests

Test concurrent requests attempting to:

- Start generation for the same project.
- Upload images to the same project.
- Delete a project during task execution.
- Register competing current results.

Database constraints must prevent inconsistent final states.

### 8.6. Migration Tests

Verify:

- Initial migration.
- Sequential migration execution.
- Upgrade to the latest schema.
- Downgrade where supported.
- Clean database initialization.

---

## 9. Integration Testing

### 9.1. General Requirements

Integration tests must verify interactions between actual application services.

Use real infrastructure dependencies where their behavior is part of the test.

Examples:

- PostgreSQL.
- Redis.
- File storage.
- Celery.
- FastAPI.

Testcontainers may be used to provision disposable PostgreSQL and Redis instances for integration tests.

An existing isolated Docker Compose test environment is also acceptable.

### 9.2. API and Database Integration

Verify:

- Project creation persists to PostgreSQL.
- Project updates are persisted.
- Image metadata is stored.
- Generation task records are created.
- Result metadata is stored.
- Cleanup jobs are persisted.

### 9.3. API and Storage Integration

Verify:

- File upload.
- File retrieval.
- File deletion.
- Unique storage paths.
- Directory traversal protection.
- File access restrictions.
- Persistent storage after service restart.

### 9.4. Redis and Celery Integration

Verify:

- Task publishing.
- Queue routing.
- Worker consumption.
- Task acknowledgement.
- Task retry.
- Worker termination.
- Task recovery.

### 9.5. Transactional Outbox Integration

Test the Outbox pattern under failure conditions.

Required scenarios:

**Scenario A — Successful Dispatch**

1. API creates a generation task.
2. API stores an outbox message.
3. Dispatcher retrieves the message.
4. Dispatcher publishes it to Redis.
5. Dispatcher marks the message as dispatched.
6. The corresponding worker receives the task.

**Scenario B — Redis Unavailable**

1. API creates a generation task.
2. Outbox message is persisted.
3. Redis is unavailable.
4. Dispatcher fails to publish the message.
5. The outbox message remains recoverable.
6. Redis becomes available.
7. Dispatcher publishes the pending message.

**Scenario C — Duplicate Publication**

1. Dispatcher publishes a message.
2. Dispatcher terminates before recording successful publication.
3. Message becomes eligible for another publication.
4. Worker receives a duplicate delivery.
5. Task execution remains idempotent.
6. No duplicate conflicting result is created.

**Scenario D — Dispatcher Restart**

1. Several messages remain pending.
2. Dispatcher is restarted.
3. All eligible messages are eventually published.
4. No message is silently discarded.

### 9.6. Worker and Storage Integration

Verify:

- Workers can access source images.
- Worker-specific directories are created.
- Generated assets are written to persistent storage.
- Storage references resolve consistently across containers.
- Cleanup jobs remove the correct files.

### 9.7. Worker and Database Integration

Verify:

- Task status changes.
- Progress stage updates.
- Atomic task claiming.
- Lease expiration.
- Error persistence.
- Result registration.
- Project lifecycle consistency.
- Stale task detection.
- Recovery after worker restarts.

### 9.8. Reliability Integration Scenarios

**Scenario E — Worker Interruption**

1. Start a generation task.
2. Allow a worker to claim it.
3. Simulate unexpected worker termination.
4. Wait until the task lease expires.
5. Run the recovery process.
6. Verify that the task is safely requeued or failed.
7. Verify that no conflicting result is created.

**Scenario F — Project Deletion During Processing**

1. Start a generation task.
2. Request project deletion.
3. Verify that the project immediately becomes inaccessible.
4. Verify that active workers stop safely.
5. Verify that source files remain available while workers use them.
6. Verify that cleanup begins after processing has stopped.
7. Verify that project metadata is eventually removed.

**Scenario G — Duplicate Idempotency Key**

1. Submit generation with an idempotency key.
2. Submit the same operation again with the same key.
3. Verify that the existing task is returned.
4. Verify that no second logical task is created.

---

## 10. Object Generation Testing

### 10.1. Testing Objective

Verify that the actual TripoSR model can generate valid 3D geometry from a single photograph.

Mocked inference is not sufficient to establish that Object Generation is implemented correctly.

### 10.2. Unit Tests

Test independently:

- Image decoding.
- EXIF orientation correction.
- RGB/RGBA conversion.
- Background removal.
- Foreground mask processing.
- Cropping.
- Image resizing.
- Model input construction.
- Mesh extraction.
- Vertex validation.
- Face validation.
- Bounding box validation.
- GLB export.
- GLB file validation.

### 10.3. Integration Tests

Execute the real TripoSR model.

At least one test must:

1. Load actual pretrained weights.
2. Load a real test photograph.
3. Execute inference.
4. Extract mesh geometry.
5. Export GLB.
6. Validate the result.

### 10.4. Test Dataset

Prepare a reproducible collection of photographs representing different object categories.

Suggested objects:

- Chair.
- Lamp.
- Bottle.
- Shoe.
- Backpack.
- Toy.
- Household appliance.
- Decorative object.

Include different capture conditions:

- Plain background.
- Complex background.
- Different lighting.
- Different object scales.
- Moderate occlusion.
- Different image dimensions.

### 10.5. Model Quality Evaluation

Evaluate the resulting 3D object using:

**Geometry**

- Non-empty geometry.
- Valid mesh topology.
- Finite vertex coordinates.
- Plausible object proportions.
- Absence of severe reconstruction artifacts.

**Appearance**

- Preserved vertex colors or materials.
- Correct appearance in the viewer.
- No major missing or corrupted appearance information.

**Visualization**

- Correct model orientation.
- Appropriate camera framing.
- Successful Three.js loading.
- No missing dependencies or textures.

Where reference 3D models are available, compare geometry using appropriate metrics.

Possible metrics:

- Chamfer Distance.
- F-score.
- Volumetric IoU.

Metric definitions and normalization must be documented before comparing different models.

Do not introduce arbitrary numerical quality thresholds before establishing a baseline on the actual TripoSR configuration.

### 10.6. GPU Testing

Execute tests on a configured GPU runner.

Measure:

- Model initialization time.
- Inference time.
- Peak VRAM consumption.
- Total generation time.
- GPU utilization.
- Worker stability after failures.

Test:

- CUDA available.
- CUDA unavailable.
- Insufficient VRAM.
- Inference timeout.
- Worker interruption.

CPU fallback must be tested separately when enabled.

### 10.7. Regression Testing

Maintain a fixed set of test photographs.

When changing:

- Model checkpoint.
- Preprocessing configuration.
- Mesh extraction resolution.
- Texture settings.
- Exporter implementation.

Run the same dataset and compare:

- Output validity.
- Mesh statistics.
- Appearance.
- Processing time.
- Memory usage.

Avoid relying on exact binary equality of generated GLB files as the only regression check.

---

## 11. Scene Reconstruction Testing

### 11.1. Testing Objective

Verify that the COLMAP + OpenMVS pipeline can reconstruct a valid textured scene from real photographs.

### 11.2. Unit Tests

Test:

- Image dataset preparation.
- Duplicate image detection.
- Image validation.
- Matching configuration.
- COLMAP command construction.
- Sparse reconstruction selection.
- Registered image count extraction.
- Camera parameter validation.
- OpenMVS command construction.
- Intermediate output validation.
- GLB export.
- Error mapping.

### 11.3. Integration Tests

Run actual COLMAP and OpenMVS binaries.

Required tests:

1. Image preparation.
2. Feature extraction.
3. Feature matching.
4. Sparse reconstruction.
5. Reconstruction selection.
6. Image undistortion.
7. OpenMVS import.
8. Dense reconstruction.
9. Mesh reconstruction.
10. Mesh refinement.
11. Texture generation.
12. GLB export.

At least one complete real reconstruction must be executed as part of release-level validation.

### 11.4. Test Datasets

Maintain several datasets.

**Dataset A — Small Interior**

A small room with sufficient visual overlap.

Purpose:

- Validate the complete reconstruction pipeline.
- Verify sparse camera estimation.
- Verify dense reconstruction.
- Validate textured GLB generation.

**Dataset B — Complex Interior**

An interior with multiple objects, different surface materials and more complex geometry.

Purpose:

- Evaluate geometric completeness.
- Evaluate texture generation.
- Identify reconstruction artifacts.

**Dataset C — Outdoor Environment**

A small static outdoor area.

Purpose:

- Verify reconstruction under different lighting conditions.
- Evaluate camera movement and scene coverage.

**Dataset D — Challenging Images**

Photographs with:

- Motion blur.
- Insufficient overlap.
- Low-texture surfaces.
- Large exposure differences.
- Duplicate images.

Purpose:

- Verify failure detection.
- Test diagnostic reporting.
- Ensure unsuccessful reconstruction is not marked as successful.

The datasets must be stored separately from production user uploads.

Record dataset origin, capture conditions and applicable usage rights.

### 11.5. Camera Reconstruction Quality

Evaluate:

- Total input images.
- Registered image count.
- Registration ratio.
- Number of reconstructed 3D points.
- Reprojection error statistics.
- Reconstruction component count.
- Camera parameter validity.

A high registered image count alone does not guarantee accurate reconstruction.

### 11.6. Dense Reconstruction Quality

Evaluate:

- Dense point cloud availability.
- Point cloud density.
- Mesh vertex count.
- Mesh face count.
- Surface completeness.
- Presence of holes.
- Geometric artifacts.
- Texture coverage.
- Texture consistency.

### 11.7. Reference-Based Evaluation

Where known reference geometry is available, evaluate reconstruction using suitable geometric comparison metrics.

Possible metrics:

- Chamfer Distance.
- F-score.
- Precision and Recall of reconstructed points.
- Surface-to-surface distance.

Define coordinate alignment and scale normalization before calculating these metrics.

For datasets without ground truth, use documented visual inspection and reconstruction diagnostics.

Do not assign an arbitrary universal quality score.

### 11.8. Reconstruction Performance

Measure:

- Feature extraction time.
- Feature matching time.
- Sparse reconstruction time.
- Undistortion time.
- OpenMVS import time.
- Dense reconstruction time.
- Mesh generation time.
- Refinement time.
- Texture generation time.
- Export time.
- Total execution time.
- Peak RAM.
- Peak VRAM when applicable.
- Temporary disk usage.

Repeat measurements for different image counts and resolutions.

### 11.9. Scene Reconstruction Regression

Maintain fixed input datasets.

Whenever changing COLMAP, OpenMVS, processing parameters or export logic, compare:

- Registered image count.
- Reconstruction statistics.
- Mesh statistics.
- Texture availability.
- Final GLB validity.
- Processing time.
- Resource consumption.

Use representative reference outputs for visual comparison.

---

## 12. GLB and 3D Asset Validation

### 12.1. General Requirements

Every generated asset must pass validation before it can be marked as a completed result.

### 12.2. Container Validation

Check:

- Valid GLB binary header.
- Correct glTF version.
- Correct total file length.
- Valid JSON chunk.
- Valid binary chunk where present.

### 12.3. Structural Validation

Check:

- Valid asset metadata.
- Valid scenes.
- Valid nodes.
- Valid mesh references.
- Valid accessors.
- Valid buffer views.
- Valid materials.
- Valid texture references.

### 12.4. Geometry Validation

Check:

- At least one mesh exists.
- At least one valid primitive exists.
- Vertex positions are valid.
- Coordinates contain no NaN or infinity.
- Face indices are valid.
- Bounding box dimensions are positive.
- Geometry is not empty.

### 12.5. Material and Texture Validation

Check:

- Materials can be parsed.
- Vertex colors are available when expected.
- UV coordinates are available when required.
- Texture references resolve correctly.
- No external texture dependency is missing.

### 12.6. Browser Compatibility

Load generated GLB files using the same Three.js/GLTFLoader implementation used by the frontend.

Verify:

- Successful parsing.
- Successful rendering.
- Correct material appearance.
- Correct texture appearance.
- Camera framing.
- Reasonable interaction performance.

### 12.7. Asset Limits

Record:

- File size.
- Number of meshes.
- Vertex count.
- Triangle count.
- Material count.
- Texture count.
- Texture dimensions.

The MVP should not reject all large assets automatically.

Instead, define tested limits based on browser capabilities and actual deployment hardware.

---

## 13. End-to-End Testing

### 13.1. Tool

Use Playwright for browser-based end-to-end testing.

The tests must interact with the application through its public interface rather than directly invoking frontend internal functions.

### 13.2. Authentication Workflow

**E2E-01. Registration**

1. Open the landing page.
2. Navigate to registration.
3. Enter valid registration data.
4. Submit the form.
5. Verify account creation.
6. Verify dashboard navigation.

**E2E-02. Login**

1. Open login page.
2. Enter registered credentials.
3. Submit the form.
4. Verify authenticated dashboard access.

**E2E-03. Logout**

1. Open authenticated page.
2. Select logout.
3. Verify session termination.
4. Verify redirection to the public page.
5. Verify protected pages are inaccessible.

### 13.3. Project Management Workflow

**E2E-04. Project Creation**

1. Authenticate.
2. Open dashboard.
3. Select Create Project.
4. Enter project name.
5. Select generation mode.
6. Upload images.
7. Create the project.
8. Verify project details.

**E2E-05. Project Listing**

Verify that:

- Project appears on dashboard.
- Name is correct.
- Type is correct.
- Creation date is displayed.
- Status is correct.

**E2E-06. Project Deletion**

1. Open a project.
2. Select delete.
3. Confirm deletion.
4. Verify project removal.
5. Verify that its assets are scheduled for cleanup.

### 13.4. Object Generation Workflow

**E2E-07. Complete Object Generation**

1. Authenticate.
2. Create an OBJECT project.
3. Upload one photograph.
4. Verify image preview.
5. Create the project.
6. Start generation.
7. Verify processing status.
8. Wait for completion within the configured test timeout.
9. Open the result.
10. Verify 3D model rendering.
11. Download the GLB asset.
12. Verify that the downloaded file is valid.

For this scenario, use actual TripoSR inference in a dedicated ML E2E environment.

### 13.5. Scene Reconstruction Workflow

**E2E-08. Complete Scene Reconstruction**

1. Authenticate.
2. Create a SCENE project.
3. Upload a representative photograph collection.
4. Verify all previews.
5. Create the project.
6. Start reconstruction.
7. Verify processing stages.
8. Wait for completion within the configured test timeout.
9. Open the result viewer.
10. Verify the scene is rendered.
11. Download the GLB.
12. Validate the downloaded asset.

For this scenario, execute the actual COLMAP/OpenMVS pipeline.

### 13.6. Failure Workflows

**E2E-09. Invalid Image**

Verify that unsupported or invalid files are rejected.

**E2E-10. Failed Generation**

Verify that failed processing is communicated correctly.

**E2E-11. Retry**

Verify that a failed generation can be restarted using existing source images.

**E2E-12. Unauthorized Access**

Verify that one user cannot open another user's project or generated assets.

### 13.7. Viewer Workflow

**E2E-13. Model Viewer**

Verify:

- GLB loading.
- Model visibility.
- Camera rotation.
- Zoom.
- Pan.
- Reset camera.
- Fit to view.
- Download.

### 13.8. E2E Test Isolation

Each workflow must use dedicated test accounts and projects.

Clean up only resources created by the test.

Never use production user data for E2E tests.

---

## 14. Performance Testing

### 14.1. API Performance

Measure response time for:

- Authentication.
- Project creation.
- Project listing.
- Project details.
- Image metadata retrieval.
- Task creation.
- Task status retrieval.
- Result metadata.

Ordinary API requests must not wait for ML processing to complete.

The following initial development target may be used:

```text
Metadata API operations:
Target response time: <= 2 seconds
```

This is a preliminary target under controlled test conditions, not a production performance guarantee.

Exclude large file transfers and ML execution from this target.

### 14.2. Upload Performance

Measure:

- Upload duration.
- File size.
- Upload failure rate.
- Storage write duration.
- Memory consumption.

Test different image sizes.

Verify that uploading multiple images does not exhaust API memory.

### 14.3. Task Processing Performance

Measure separately:

**Object Generation**

- Model initialization.
- Preprocessing.
- Inference.
- Mesh extraction.
- Export.

**Scene Reconstruction**

- Feature extraction.
- Matching.
- Sparse reconstruction.
- Dense reconstruction.
- Mesh processing.
- Texturing.
- Export.

### 14.4. Viewer Performance

Evaluate:

- Initial GLB loading time.
- Model parsing time.
- Initial render time.
- Camera interaction responsiveness.
- Memory consumption.
- Behavior when changing models.

Test both small individual objects and larger scenes.

### 14.5. Resource Stress Tests

Evaluate:

- Multiple simultaneous image uploads.
- Multiple pending generation tasks.
- Worker concurrency.
- Large reconstruction datasets.
- Limited GPU memory.
- Limited RAM.
- Limited available disk space.
- Repeated viewer model loading.

### 14.6. Performance Baselines

Establish baseline measurements using fixed hardware and fixed datasets.

Every optimization must be evaluated against these baselines.

Do not compare measurements obtained from substantially different hardware without clearly identifying the differences.

Do not introduce arbitrary performance claims before actual measurements exist.

---

## 15. Security Testing

### 15.1. Authentication

Verify:

- Invalid credentials are rejected.
- Expired sessions are rejected.
- Revoked sessions are rejected.
- Logout invalidates the session.
- Session identifiers are not exposed through frontend JavaScript.
- Cookie security attributes are configured correctly.

### 15.2. Authorization

Test:

- Unauthorized project retrieval.
- Unauthorized project modification.
- Unauthorized project deletion.
- Unauthorized image retrieval.
- Unauthorized result download.
- Access to another user's task.
- Access to another user's stored files.

### 15.3. File Upload Security

Test:

- Executable file with JPEG extension.
- Invalid image content.
- MIME type mismatch.
- Oversized files.
- Excessive image dimensions.
- Path traversal attempts.
- Filename manipulation.
- Malformed files.

### 15.4. API Security

Test:

- Missing authentication.
- Invalid authorization.
- CSRF token validation.
- CORS restrictions.
- Request validation.
- Excessive task initiation.
- Duplicate generation requests.

### 15.5. Container Security

Verify:

- No production secrets in the image.
- No unnecessary public ports.
- No unrestricted storage mounts.
- No unnecessary root execution.
- No exposed Redis or PostgreSQL endpoints in production.

### 15.6. Security Regression

Security tests must be repeated after changes involving:

- Authentication.
- Session handling.
- File storage.
- Authorization.
- API endpoints.
- Container configuration.

---

## 16. Reliability and Failure Recovery Testing

### 16.1. API Failure

Verify that an API interruption does not corrupt already persisted project data.

### 16.2. Redis Failure

Verify that pending outbox messages remain recoverable when Redis is unavailable.

### 16.3. Worker Failure

Test unexpected worker termination during:

- Model inference.
- Sparse reconstruction.
- Dense reconstruction.
- Mesh generation.
- Texture generation.
- Result registration.

### 16.4. Storage Failure

Test:

- Missing input files.
- Inaccessible storage directory.
- Failed file writes.
- Incomplete cleanup.
- Missing generated assets.

### 16.5. Database Failure

Test database connection interruption during task execution and result persistence.

Workers must not mark a task as completed when result metadata cannot be persisted.

### 16.6. Stale Task Detection

Verify that tasks stuck in PROCESSING can be identified.

Recovery logic must:

- Inspect heartbeat information.
- Inspect lease expiration.
- Determine whether the worker is still active.
- Inspect available output artifacts.
- Decide whether to resume, retry or fail.
- Preserve previous successful results.

### 16.7. Recovery Testing

After restarting affected services, verify:

- Task states remain consistent.
- Pending tasks are dispatched.
- Duplicate task execution does not create conflicting results.
- Cleanup operations remain recoverable.
- Completed assets remain accessible.

### 16.8. Required Reliability Scenarios

The following scenarios must be covered by automated reliability tests:

- Dispatcher termination after successful Redis publication.
- Duplicate Celery message delivery.
- Expired worker lease.
- Worker recovery after process termination.
- Cancellation during project deletion.
- Orphaned generated asset cleanup.

---

## 17. Test Execution Profiles

### 17.1. Fast Profile

Purpose: run frequently during development.

Includes:

- Frontend unit tests.
- Backend unit tests.
- API tests with mocked infrastructure.
- Static analysis.
- Type checking.
- Build validation.

Does not require:

- GPU.
- TripoSR weights.
- Full COLMAP/OpenMVS execution.

### 17.2. Integration Profile

Purpose: verify service interactions.

Includes:

- PostgreSQL.
- Redis.
- FastAPI.
- Celery.
- Shared storage.
- Transactional Outbox.
- Migration tests.

ML adapters may be mocked.

### 17.3. E2E Profile

Purpose: verify complete user workflows.

Includes:

- Frontend.
- Backend.
- Database.
- Redis.
- Workers.
- Browser tests.

Ordinary E2E workflows may use predefined valid GLB fixtures and controlled processing adapters.

### 17.4. ML Profile

Purpose: validate actual generation algorithms.

Includes:

- TripoSR real inference.
- COLMAP processing.
- OpenMVS processing.
- GLB validation.
- Dataset-based quality evaluation.

GPU tests require suitable hardware.

Scene reconstruction tests should use fixed datasets.

### 17.5. Release Profile

Purpose: verify release readiness.

Includes:

- All required fast tests.
- Integration tests.
- E2E smoke tests.
- Actual TripoSR inference.
- Actual COLMAP/OpenMVS reconstruction.
- GLB validation.
- Security regression.
- Performance comparison.
- Docker Compose deployment verification.

A release must not be considered fully validated when mandatory real ML integration tests have never been executed.

---

## 18. CI/CD Testing Pipeline

### 18.1. General Requirements

Automate repeatable quality checks.

Use the repository's selected CI platform.

The pipeline must distinguish fast tests from resource-intensive tests.

### 18.2. Pull Request Checks

Every pull request should execute:

1. Frontend linting.
2. Frontend type checking.
3. Frontend unit tests.
4. Frontend production build.
5. Backend linting.
6. Backend type checking.
7. Backend unit tests.
8. Backend API tests with test dependencies.
9. Database migration validation.
10. Infrastructure configuration validation.

Database migration validation must include the `OutboxMessage` schema and all composite ownership constraints.

### 18.3. Integration Pipeline

Run integration checks in a dedicated environment.

Required operations:

- Start PostgreSQL.
- Start Redis.
- Apply migrations.
- Run database integration tests.
- Run API integration tests.
- Run Celery integration tests.
- Run Outbox recovery tests.
- Verify real PostgreSQL locking behavior, including `FOR UPDATE SKIP LOCKED` and atomic task claiming.
- Stop test services.

### 18.4. ML Validation Pipeline

Run ML tests on suitable runners.

Object Generation:

- Initialize TripoSR.
- Execute representative inference.
- Validate generated GLB.
- Measure VRAM and execution duration.

Scene Reconstruction:

- Run representative COLMAP processing.
- Run OpenMVS processing.
- Validate textured mesh.
- Export GLB.
- Validate browser compatibility.

### 18.5. Release Checks

Before release, verify:

- No critical failing tests.
- No unresolved migration errors.
- No broken application workflows.
- No invalid generated assets.
- No known critical security issues.
- Real ML integrations work in their supported environment.
- Docker images build successfully.
- Worker recovery and duplicate message handling are verified.

### 18.6. Test Reports

Publish:

- Test summaries.
- Failed test logs.
- Coverage reports.
- ML processing metrics.
- Reconstruction diagnostics.
- Build reports.

Do not include secrets or private user images in CI artifacts.

---

## 19. Code Coverage Requirements

### 19.1. General Policy

Use code coverage as a quality indicator, not as the only measure of testing quality.

Coverage must not replace behavioral testing.

### 19.2. Initial Targets

Suggested development targets:

| Component | Initial Target |
|---|---:|
| Backend business services | 80% |
| Backend repositories | 75% |
| Backend API handlers | 75% |
| Image validation logic | 90% |
| Generation state management | 90% |
| Frontend shared utilities | 80% |
| Frontend business logic | 80% |

These values are initial project targets.

Do not force artificial tests solely to increase a percentage.

### 19.3. Critical Code

Critical functionality must receive dedicated tests regardless of overall coverage.

Examples:

- Project ownership validation.
- Session validation.
- Generation task creation.
- Duplicate task prevention.
- Result replacement.
- File cleanup.
- Worker recovery.
- GLB validation.

---

## 20. Test Commands

### 20.1. Backend

Run all backend tests:

```bash
pytest backend/tests -v
```

Run unit tests:

```bash
pytest backend/tests/unit -v
```

Run API tests:

```bash
pytest backend/tests/api -v
```

Run integration tests:

```bash
pytest backend/tests/integration -v -m integration
```

Run coverage:

```bash
pytest backend/tests \
  --cov=app \
  --cov-report=term-missing
```

### 20.2. ML

Run object generation tests:

```bash
pytest ml/object_generation/tests -v
```

Run scene reconstruction tests:

```bash
pytest ml/scene_reconstruction/tests -v
```

Run GPU tests:

```bash
pytest ml -v -m gpu
```

Run slow tests:

```bash
pytest ml -v -m slow
```

### 20.3. Frontend

Run unit tests:

```bash
npm run test:run
```

Run linting:

```bash
npm run lint
```

Run type checking:

```bash
npm run typecheck
```

Run production build:

```bash
npm run build
```

### 20.4. End-to-End

Run Playwright tests:

```bash
npx playwright test
```

Run a specific workflow:

```bash
npx playwright test object-generation.spec.ts
```

### 20.5. Infrastructure

Validate Compose:

```bash
docker compose config
```

Start the test environment:

```bash
docker compose --profile test up -d --build
```

Inspect services:

```bash
docker compose ps
```

Run integration checks:

```bash
docker compose exec api pytest tests/integration -v
```

The exact commands must be aligned with the final repository structure and configured Compose profiles.

---

## 21. Acceptance Criteria

### TEST-AC-01. Test Infrastructure

The repository contains organized test suites for frontend, backend, ML modules and end-to-end workflows.

### TEST-AC-02. Unit Tests

Frontend and backend unit tests execute independently without requiring real ML inference.

### TEST-AC-03. API Tests

Required API endpoints have tests for successful and unsuccessful request scenarios.

### TEST-AC-04. Authorization Tests

Project and asset ownership restrictions are covered by automated tests.

### TEST-AC-05. Database Tests

Database entities, relationships, constraints and migrations are verified.

### TEST-AC-06. Task Lifecycle Tests

All generation task status transitions are tested.

### TEST-AC-07. Duplicate Protection

Concurrent generation requests cannot create conflicting active tasks for the same project.

### TEST-AC-08. Outbox Reliability

The Transactional Outbox mechanism is tested under Redis interruptions and duplicate dispatch.

### TEST-AC-09. Storage Tests

Uploads, downloads, persistence and cleanup operations are tested.

### TEST-AC-10. Frontend Tests

All primary reusable frontend components and business logic have automated tests.

### TEST-AC-11. Viewer Tests

The frontend can load, display and interact with valid GLB fixtures.

### TEST-AC-12. TripoSR Integration

At least one test executes the real TripoSR model with pretrained weights.

### TEST-AC-13. Scene Reconstruction Integration

At least one test executes a complete real COLMAP/OpenMVS reconstruction.

### TEST-AC-14. GLB Validation

Both object and scene generation results pass structural and geometry validation.

### TEST-AC-15. End-to-End Testing

The primary object and scene generation user workflows are covered.

### TEST-AC-16. Performance Measurement

Generation duration, resource consumption and output characteristics can be measured.

### TEST-AC-17. Failure Recovery

Worker interruption and processing failures do not cause permanent inconsistent task states.

### TEST-AC-18. Previous Result Preservation

Failed regeneration attempts do not remove previously successful assets.

### TEST-AC-19. CI/CD Integration

Fast quality checks execute automatically for code changes.

### TEST-AC-20. Release Validation

A release can be validated using real ML processing, infrastructure and browser-based tests.

---

## 22. Implementation Order

### Phase 1. Testing Infrastructure

- Configure pytest.
- Configure Vitest.
- Configure React Testing Library.
- Configure Playwright.
- Configure test environment variables.
- Create test fixtures.
- Register pytest markers.

### Phase 2. Backend Unit Tests

- Test services.
- Test repositories.
- Test validation.
- Test authentication.
- Test project state management.
- Test task logic.

### Phase 3. Frontend Tests

- Test common components.
- Test forms.
- Test project management.
- Test image uploading.
- Test generation states.
- Test viewer utilities.

### Phase 4. API and Database Tests

- Test endpoints.
- Test authorization.
- Test database constraints.
- Test migrations.
- Test file management.
- Test task creation.

### Phase 5. Integration Tests

- Start PostgreSQL and Redis.
- Test Celery queues.
- Test workers.
- Test shared storage.
- Test Transactional Outbox.
- Test failure recovery.

### Phase 6. ML Tests

- Prepare object test dataset.
- Run real TripoSR inference.
- Validate generated meshes.
- Prepare scene test datasets.
- Run real COLMAP reconstruction.
- Run OpenMVS processing.
- Validate textured GLB outputs.

### Phase 7. End-to-End Tests

- Test registration.
- Test authentication.
- Test project creation.
- Test object generation.
- Test scene reconstruction.
- Test result visualization.
- Test model download.
- Test failure and retry workflows.

### Phase 8. Final Quality Assurance

- Measure code coverage.
- Measure generation performance.
- Inspect representative 3D results.
- Run security tests.
- Run Docker deployment tests.
- Run release validation.
- Document known limitations.

---

## 23. Related Specifications

This document defines the overall application testing strategy.

Related documents:

- `00_project_overview.md` — project context.
- `01_product_requirements.md` — product requirements.
- `02_ui_ux_specification.md` — UI/UX requirements.
- `03_frontend_specification.md` — frontend implementation.
- `04_backend_specification.md` — backend implementation.
- `05_database_specification.md` — database architecture.
- `06_object_generation.md` — TripoSR integration.
- `07_scene_reconstruction.md` — COLMAP/OpenMVS integration.
- `08_infrastructure.md` — deployment architecture.
- `10_development_roadmap.md` — implementation sequence.
- `AI_DEVELOPMENT_GUIDE.md` — development workflow, quality gates and agent rules.

All components must meet the testing and quality requirements defined in this document.