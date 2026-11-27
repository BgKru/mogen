# 10 — Development Roadmap

## 1. Document Purpose

This document defines the implementation roadmap for the 3D generation web application.

It combines the requirements and architecture decisions from all previous specifications into an ordered development plan.

It describes:

- Development phases.
- Implementation priorities.
- Dependencies between development tasks.
- Expected deliverables.
- Milestones.
- Acceptance criteria.
- Integration strategy.
- Testing checkpoints.
- Release readiness requirements.

The objective is to organize development into manageable stages and ensure that every stage produces a functional and verifiable result.

This document defines the order of implementation.

Detailed implementation requirements remain in the corresponding subsystem specifications.

---

## 2. Development Principles

### 2.1. Incremental Development

Implement the application incrementally.

Each development phase must produce a working and testable result.

Avoid implementing the entire application in one large development cycle.

### 2.2. Vertical Slice Approach

Prefer implementing complete functional workflows rather than completing entire technical layers independently.

For example, project creation should include:

- Frontend form.
- API endpoint.
- Backend validation.
- Database persistence.
- Dashboard update.
- Automated tests.

This approach makes integration problems visible early.

### 2.3. Specification-Driven Development

All implementation work must follow the project specifications.

Before starting a development phase:

1. Read `00_project_overview.md`.
2. Read the relevant subsystem specifications.
3. Identify dependencies on other modules.
4. Review existing code.
5. Prepare an implementation plan.
6. Implement the required functionality.
7. Execute relevant tests.
8. Update documentation where necessary.

Do not introduce architectural changes without documenting their impact on related components.

### 2.4. Functional Completeness

A feature is not complete merely because its interface has been implemented.

For example, an image upload feature is complete only when:

- The frontend allows image selection.
- The backend validates the image.
- The file is stored persistently.
- Metadata is saved in PostgreSQL.
- The uploaded image can be retrieved through an authorized operation.
- Error scenarios are handled.

### 2.5. No Fake Functionality

The application must not use fake functionality as a substitute for the actual implementation.

Examples of prohibited substitutes:

- Static GLB files presented as newly generated models.
- Simulated generation completion.
- Artificial processing percentages.
- Fake reconstruction stages.
- Hardcoded project data in production functionality.
- Mocked ML inference presented as actual TripoSR processing.

Mocks and test fixtures are permitted exclusively in testing and explicitly identified development demonstrations.

### 2.6. Modular Architecture

Maintain clear separation between:

- Frontend.
- Backend.
- Database.
- File Storage.
- Background Processing.
- Object Generation.
- Scene Reconstruction.
- Infrastructure.

Avoid unnecessary coupling.

### 2.7. Continuous Testing

Run relevant automated tests after implementing each feature.

Do not postpone all testing until the final development phase.

---

## 3. Development Priorities

Use the following priority levels:

| Priority | Meaning |
|---|---|
| P0 | Mandatory for MVP |
| P1 | Important, but may follow core functionality |
| P2 | Future improvement |

All mandatory MVP functionality must be completed before release.

### 3.1. P0 — Mandatory Features

- Project repository initialization.
- Docker Compose infrastructure.
- PostgreSQL database.
- Redis broker.
- FastAPI backend.
- React frontend.
- Authentication.
- Project management.
- Image uploading.
- TripoSR object generation.
- COLMAP scene reconstruction.
- OpenMVS mesh and texture generation.
- Celery background processing.
- Three.js viewer.
- GLB export and download.
- Error handling.
- Persistent file storage.
- Essential automated tests.

### 3.2. P1 — Important Improvements

- Detailed generation diagnostics.
- Advanced upload feedback.
- Better reconstruction quality warnings.
- Historical generation result management in the interface.
- Scene splitting for large reconstruction datasets.
- More detailed processing metrics.
- Improved browser rendering performance.
- Additional export formats.

### 3.3. P2 — Future Development

- Semantic scene segmentation.
- Independent object extraction from reconstructed scenes.
- Manual mesh editing.
- Advanced scene composition.
- Text-to-3D generation.
- Video-based reconstruction.
- Gaussian Splatting.
- NeRF-based visualization.
- Collaborative editing.
- Public asset sharing.
- S3-compatible storage migration.
- Distributed GPU worker infrastructure.
- Kubernetes deployment.

P1 and P2 features must not delay the implementation of the mandatory MVP functionality unless they are required to resolve a critical technical limitation.

---

## 4. Development Architecture Overview

The roadmap must follow the established application architecture.

```text
                    FRONTEND
                       |
                       v
                   FASTAPI
                       |
          +------------+------------+
          |                         |
          v                         v
      POSTGRESQL               FILE STORAGE
          |
          v
    OUTBOX MESSAGES
          |
          v
    OUTBOX DISPATCHER
          |
          v
         REDIS
          |
     +----+----------------+
     |                     |
     v                     v
OBJECT WORKER          SCENE WORKER
     |                     |
     v                     v
  TripoSR              COLMAP
     |                     |
     v                     v
  Mesh Export           OpenMVS
     |                     |
     v                     v
   GLB Asset            GLB Asset
     |                     |
     +----------+----------+
                |
                v
          FILE STORAGE
                |
                v
           POSTGRESQL
                |
                v
          FRONTEND VIEWER
```

The architecture must support independent implementation and deployment of the main subsystems.

---

## 5. Development Phases

The implementation is divided into eleven phases.

Each phase has:

- Objectives.
- Implementation tasks.
- Expected deliverables.
- Dependencies.
- Acceptance criteria.

A phase is considered complete only when its deliverables have been implemented and verified.

---

# PHASE 0. Specification Consolidation and Architecture Decisions

Priority: P0

### Objective

Review all specifications and resolve architectural inconsistencies before implementing the application.

The existing documents provide the initial requirements, but some cross-component details need to be formalized.

### Tasks

**0.1. Review Existing Specifications**

Review:

- Project Overview.
- Product Requirements.
- UI/UX Specification.
- Frontend Specification.
- Backend Specification.
- Database Specification.
- Object Generation Specification.
- Scene Reconstruction Specification.
- Infrastructure Specification.
- Testing Specification.

Identify conflicting requirements and missing technical contracts.

**0.2. Create Architecture Documents**

Create the following supporting documents:

```text
docs/
│
└── architecture/
    ├── system_architecture.md
    ├── api_contracts.md
    └── data_flow.md
```

`system_architecture.md` must describe the final component architecture and communication boundaries.

`api_contracts.md` must contain the canonical REST API request and response schemas.

`data_flow.md` must describe the main data flows, including image uploading, generation task execution, result persistence and downloading.

**0.3. Extend Database Specification**

Add the `outbox_messages` table to the Database Specification.

Define:

- Outbox message structure.
- Message types.
- Publishing status.
- Retry behavior.
- Duplicate publication handling.
- Dispatcher responsibilities.

**0.4. Resolve Task Lifecycle**

Define a single consistent model for project and generation task states.

Clarify:

- Project status.
- Generation task status.
- Processing stage.
- Previous successful result preservation.
- Retry behavior.
- Worker interruption recovery.

**0.5. Finalize API Contracts**

Define:

- Authentication payloads.
- Cookie and CSRF behavior.
- Project creation requests.
- Image upload requests.
- Generation task responses.
- Status responses.
- Result metadata.
- Download behavior.
- Error response format.
- Pagination parameters.

**0.6. Verify Third-Party Dependencies**

Before implementation, review:

- TripoSR repository and model revision.
- PyTorch and CUDA compatibility.
- COLMAP version.
- OpenMVS version.
- OpenMVS licensing implications.
- OpenMVS GLB export support.
- Python dependency compatibility.

**0.7. Define Development Hardware Profile**

Document the expected development environment:

- CPU.
- RAM.
- GPU.
- VRAM.
- Available disk space.
- Operating system.
- Docker environment.

Do not assume GPU availability on every deployment.

**0.8. Finalize Cross-Cutting Contracts**

Define and document:

- Final CSRF cookie implementation (signed double-submit, session binding, rotation).
- Worker lease and recovery behavior.
- Internal task cancellation.
- Project deletion coordination with active workers.
- Composite database ownership constraints.
- Generation request fingerprint rules.
- Verified OpenMVS GLB export using the pinned version.

### Deliverables

- Reviewed specification set.
- `system_architecture.md`.
- `api_contracts.md`.
- `data_flow.md`.
- Updated Database Specification.
- Initial dependency and licensing decisions.
- Documented hardware requirements.
- `architecture/phase0_decisions.md` — audit evidence, pinned versions, licensing and hardware profile.

### Acceptance Criteria

- All subsystem specifications use consistent terminology.
- API contracts are defined.
- Database entities support all required workflows.
- Outbox functionality is reflected in the database model.
- ML dependencies have a documented compatibility strategy.
- No critical architectural conflicts remain unresolved.

### Dependencies

None.

This phase must be completed before major implementation work begins.

---

# PHASE 1. Repository Initialization and Infrastructure Foundation

Priority: P0

### Objective

Create the initial project repository and establish a working Docker-based development environment.

The application must be launchable before implementing complex business functionality.

### Tasks

**1.1. Repository Structure**

Create the project directory structure:

```text
project/
│
├── docs/
│   ├── specifications/
│   └── architecture/
│
├── frontend/
│
├── backend/
│
├── ml/
│   ├── object_generation/
│   ├── scene_reconstruction/
│   └── workers/
│
├── infrastructure/
│   ├── docker/
│   ├── nginx/
│   └── scripts/
│
├── tests/
│
├── compose.yaml
├── compose.gpu.yaml
├── .env.example
├── .gitignore
└── README.md
```

**1.2. Git Configuration**

- Initialize the Git repository.
- Create the main development branch.
- Add `.gitignore`.
- Exclude `.env` files.
- Exclude model checkpoints.
- Exclude uploaded user images.
- Exclude temporary processing artifacts.
- Exclude generated production assets.

**1.3. Frontend Initialization**

Initialize:

- React.
- TypeScript.
- Vite.
- Tailwind CSS.
- ESLint.
- Prettier.
- React Router.
- TanStack Query.

Verify that the frontend can start independently.

**1.4. Backend Initialization**

Initialize:

- Python environment.
- FastAPI.
- Pydantic Settings.
- SQLAlchemy.
- Alembic.
- Uvicorn.
- HTTPX.
- Pytest.

Implement a minimal FastAPI application.

**1.5. Database Infrastructure**

Configure:

- PostgreSQL Docker image.
- Environment variables.
- Persistent volume.
- Health check.
- Internal network.

**1.6. Redis Infrastructure**

Configure:

- Redis Docker image.
- Persistent volume.
- Health check.
- Internal network.

**1.7. Docker Compose**

Create:

- Main Compose file.
- GPU override configuration.
- Development configuration.
- Initial application volumes.
- Internal service network.

**1.8. Health Checks**

Implement initial health endpoints.

The application must be able to report whether its essential infrastructure dependencies are available.

### Deliverables

- Initialized Git repository.
- Running React application.
- Running FastAPI application.
- PostgreSQL container.
- Redis container.
- Initial Docker Compose environment.
- Environment configuration template.

### Acceptance Criteria

- `docker compose config` completes successfully.
- All initial services can be built.
- Frontend is accessible.
- FastAPI health endpoint responds.
- PostgreSQL accepts connections.
- Redis passes its health check.
- Persistent volumes work across container recreation.

### Dependencies

Phase 0.

---

# PHASE 2. Database and Backend Foundation

Priority: P0

### Objective

Implement the persistent data model and establish the primary backend functionality.

### Tasks

**2.1. Database Models**

Implement SQLAlchemy models:

- User.
- UserSession.
- Project.
- ProjectImage.
- GenerationTask.
- GenerationTaskImage.
- GenerationResult.
- StorageCleanupJob.
- OutboxMessage.

**2.2. Database Migrations**

Create the initial Alembic migration.

Implement:

- Primary keys.
- Foreign keys.
- Unique constraints.
- Check constraints.
- Partial unique indexes.
- Required query indexes.

Verify clean database initialization.

**2.3. Repository Layer**

Implement repositories for all primary database entities.

Separate database queries from business logic.

**2.4. Authentication**

Implement:

- User registration.
- Password hashing.
- Login.
- Session creation.
- Session validation.
- CSRF protection.
- Current user endpoint.
- Logout.
- Session revocation.

**2.5. Project Management API**

Implement:

- Project creation.
- Project listing.
- Pagination.
- Filtering.
- Project details.
- Project deletion.

**2.6. Authorization**

Implement ownership validation.

Ensure that users can access only their own projects.

**2.7. File Storage Abstraction**

Implement:

- Storage interface.
- Local filesystem backend.
- Unique storage keys.
- File saving.
- File retrieval.
- File deletion.
- Storage existence checks.
- Storage path validation.

**2.8. Image Upload**

Implement:

- Multipart file upload.
- JPEG validation.
- PNG validation.
- Image decoding.
- File size restrictions.
- Image dimension restrictions.
- SHA-256 calculation.
- Image metadata persistence.

Support:

- Single-image Object Generation projects.
- Multiple-image Scene Reconstruction projects.

**2.9. Cleanup Jobs**

Implement persistent cleanup job creation and storage.

The actual cleanup worker will be integrated in a later phase.

**2.10. Task Resilience and Ownership Metadata**

Implement in the initial schema and ORM models:

- Outbox insertion inside the generation transaction.
- Project-scoped idempotency (`idempotency_key` and `request_fingerprint`).
- Composite foreign key constraints for task-image and result-task ownership.
- Task lease metadata (`worker_id`, `heartbeat_at`, `lease_expires_at`, `attempt_count`).
- Cancellation metadata (`cancel_requested_at`).

### Deliverables

- Complete initial database schema.
- Alembic migrations.
- Authentication API.
- Project API.
- Image upload API.
- Local file storage.
- Authorization.
- Backend unit and API tests.

### Acceptance Criteria

- Users can register and authenticate.
- Users can create projects.
- Projects persist in PostgreSQL.
- Images are stored in persistent storage.
- Uploaded image metadata is persisted.
- File validation works.
- Users cannot access other users' projects.
- All related unit and API tests pass.

### Dependencies

Phase 1.

---

# PHASE 3. Frontend Application and Backend Integration

Priority: P0

### Objective

Implement the primary application interface and connect it to the actual backend API.

This phase must produce a usable application without ML generation functionality yet.

### Tasks

**3.1. Application Layout**

Implement:

- Global application shell.
- Sidebar.
- Topbar.
- Main content area.
- Navigation.
- Dark theme.
- Design tokens.

**3.2. Authentication Pages**

Implement:

- Landing page.
- Registration page.
- Login page.
- Authentication state initialization.
- Protected routes.
- Logout.

Integrate all operations with FastAPI.

**3.3. Project Dashboard**

Implement:

- Project listing.
- Project cards.
- Project type indicators.
- Status indicators.
- Empty state.
- Delete confirmation dialog.

**3.4. Project Creation**

Implement:

- Generation mode selection.
- Project name input.
- Form validation.
- Object Generation upload interface.
- Scene Reconstruction upload interface.

**3.5. Image Upload Integration**

Implement:

- Drag and drop.
- File selection.
- Image previews.
- Single-image mode.
- Multiple-image mode.
- Image removal.
- Upload progress.
- Upload error handling.

Integrate with the actual backend upload API.

**3.6. Project Details**

Implement:

- Project metadata.
- Uploaded image collection.
- Current status.
- Generation action placeholders only where the backend has not yet exposed generation functionality.
- Error and empty states.

Do not display generation as available until the backend endpoint exists.

### Deliverables

- Functional React application.
- Authentication interface.
- Project dashboard.
- Project creation workflow.
- Image uploading.
- Project details page.
- Frontend tests.

### Acceptance Criteria

- Users can register and log in through the interface.
- Dashboard displays projects retrieved from PostgreSQL through the API.
- Both generation modes can be selected.
- Correct upload functionality is displayed for each mode.
- Images can be uploaded and previewed.
- Projects can be opened and deleted.
- No hardcoded production project data remains.

### Dependencies

Phase 2.

Frontend and backend implementation may proceed in parallel after the API contracts have been finalized.

---

# PHASE 4. Background Processing Infrastructure

Priority: P0

### Objective

Implement asynchronous task processing before integrating real ML algorithms.

The application must be able to create, queue, track and recover background tasks.

### Tasks

**4.1. Celery Configuration**

Configure:

- Celery application.
- Redis broker.
- Task serialization.
- Queue routing.
- Timeouts.
- Bounded retries.
- Worker logging.

**4.2. Queue Separation**

Create queues:

```text
object_generation
scene_reconstruction
file_cleanup
```

**4.3. Worker Containers**

Create dedicated worker service definitions.

Implement initial worker environments and readiness checks.

Do not simulate real ML processing in these workers.

**4.4. Transactional Outbox**

Implement:

- OutboxMessage database model.
- Outbox message repository.
- Transactional outbox insertion.
- Dispatcher process.
- Message publishing.
- Retry logic.
- Duplicate delivery handling.

**4.5. Task Lifecycle**

Implement:

- GenerationTask creation.
- GenerationTaskImage snapshot creation.
- Project state transitions.
- Task status updates.
- Task ownership.
- Duplicate execution prevention.
- Idempotency key handling.

**4.6. Task Status API**

Implement:

`POST /api/v1/projects/{id}/generate`

`GET /api/v1/projects/{id}/status`

The generation endpoint must return HTTP 202 when a task has been successfully accepted for background execution.

**4.7. Failure Handling**

Implement:

- Worker heartbeat.
- Detection of stale tasks.
- Worker interruption recovery.
- Task failure recording.
- Manual retry workflow.
- Previous result preservation.

**4.8. Cleanup Worker**

Implement the cleanup worker and connect it to persistent cleanup jobs.

**4.9. Task Recovery and Lease Management**

Implement:

- Outbox Dispatcher hardening (claim commit before publish, expired lock recovery).
- Task Recovery service.
- Atomic task claiming.
- Heartbeat updates.
- Lease expiration.
- Internal cancellation.
- Duplicate task delivery protection.

### Deliverables

- Celery infrastructure.
- Redis queues.
- Outbox dispatcher.
- Task persistence.
- Task lifecycle management.
- Task status API.
- Cleanup worker.
- Task Recovery service.
- Worker recovery logic.

### Acceptance Criteria

- Tasks can be created through the API.
- Tasks are persisted in PostgreSQL.
- Dispatcher sends messages to Redis.
- Correct workers consume corresponding queues.
- Task states update correctly.
- Duplicate generation requests do not create conflicting tasks.
- Temporary Redis failure does not permanently lose an outbox message.
- Interrupted tasks can be detected and recovered.
- Cleanup jobs execute correctly.

### Dependencies

Phase 2.

Phase 3 may be developed in parallel.

---

# PHASE 5. Object Generation — TripoSR Integration

Priority: P0

### Objective

Implement actual 3D object generation using the TripoSR model.

This is the first real ML capability of the application.

### Tasks

**5.1. Environment Preparation**

- Clone official TripoSR repository.
- Pin repository revision.
- Configure Python runtime.
- Install dependencies.
- Configure PyTorch.
- Configure CUDA.
- Download pretrained weights.
- Verify model initialization.

**5.2. Standalone Inference**

Before integrating with the application:

1. Load a real test photograph.
2. Execute TripoSR.
3. Extract mesh geometry.
4. Export a GLB file.
5. Open the resulting asset in a compatible viewer.

This standalone test is mandatory.

Do not proceed to full backend integration until real inference and export have been demonstrated.

**5.3. Image Preprocessing**

Implement:

- Image decoding.
- EXIF correction.
- Background removal.
- Foreground detection.
- Cropping.
- Resizing.
- Model input preparation.

**5.4. Model Integration**

Implement:

- Model loader.
- Persistent weight cache.
- CUDA device management.
- Inference execution.
- Chunk size configuration.
- VRAM management.

**5.5. Mesh Extraction**

Implement:

- Surface extraction.
- Mesh validation.
- Normal generation where necessary.
- Bounding box calculation.
- Geometry validation.

**5.6. GLB Export**

Implement:

- GLB generation.
- Appearance preservation.
- Vertex color export.
- Optional texture baking.
- Final asset validation.

**5.7. Celery Integration**

Implement:

`generate_object_task`

Connect TripoSR to the existing background task architecture.

**5.8. Result Persistence**

Integrate:

- Storage of generated assets.
- GenerationResult creation.
- Task status updates.
- Project status updates.
- Result availability.
- Failure handling.
- Retry support.

**5.9. Frontend Integration**

Connect the object generation workflow to the actual backend.

Implement:

- Start generation action.
- Processing status.
- Stage reporting.
- Failure state.
- Retry action.
- Result availability.

### Deliverables

- Working TripoSR worker.
- Actual single-image 3D generation.
- GLB export.
- Database result persistence.
- Frontend integration.
- GPU error handling.
- Object generation tests.

### Acceptance Criteria

- A real photograph can be processed through TripoSR.
- The model generates valid geometry.
- A valid GLB file is exported.
- The result is stored persistently.
- Task status updates correctly.
- A failed generation does not corrupt the project.
- The result can be downloaded through the API.

### Dependencies

Phases 2 and 4.

Phase 1 must provide the required GPU-capable Docker environment for hardware-based validation.

---

# PHASE 6. Scene Reconstruction — COLMAP and OpenMVS Integration

Priority: P0

### Objective

Implement actual photogrammetric reconstruction of entire environments.

This is the second major ML capability and the primary product differentiator.

### Tasks

**6.1. Environment Preparation**

- Install COLMAP.
- Install OpenMVS.
- Install native dependencies.
- Pin compatible versions.
- Verify external executables.
- Prepare sample photographs.
- Verify available CPU and GPU resources.

**6.2. Standalone COLMAP Pipeline**

Implement and test:

- Feature extraction.
- Feature matching.
- Sparse reconstruction.
- Reconstruction selection.
- Camera validation.
- Image undistortion.

**6.3. Sparse Reconstruction Diagnostics**

Implement:

- Registered image count.
- Registration ratio.
- Point cloud statistics.
- Reconstruction component detection.
- Camera parameter checks.

Reject invalid or unusable reconstruction results.

**6.4. OpenMVS Integration**

Implement:

- InterfaceCOLMAP import.
- Dense point cloud reconstruction.
- Mesh generation.
- Mesh refinement.
- Texture generation.

**6.5. GLB Export**

Implement:

- Scene conversion.
- GLB export.
- Material validation.
- Texture validation.
- Geometry validation.
- Asset checksum calculation.

**6.6. Pipeline Orchestration**

Implement `PhotogrammetryReconstructor`.

The pipeline must execute individual reconstruction stages in the correct order.

Each stage must have:

- Input validation.
- Execution timeout.
- Log capture.
- Output validation.
- Error handling.

**6.7. Checkpointing**

Preserve validated intermediate outputs.

Allow recovery from interrupted reconstruction tasks where safe.

**6.8. Celery Integration**

Implement:

`reconstruct_scene_task`

Connect the complete pipeline to the Scene Worker.

**6.9. Frontend Integration**

Implement:

- Scene reconstruction initiation.
- Actual processing stage display.
- Reconstruction errors.
- Retry functionality.
- Result availability.

### Deliverables

- Working Scene Worker.
- COLMAP integration.
- OpenMVS integration.
- Textured mesh generation.
- GLB export.
- Task status reporting.
- Reconstruction diagnostics.
- Frontend integration.

### Acceptance Criteria

- Multiple photographs can be processed.
- COLMAP produces a valid sparse reconstruction.
- Camera parameters are available.
- OpenMVS produces dense geometry.
- A valid mesh is generated.
- Texture generation completes successfully.
- GLB export produces a valid scene asset.
- The result is stored in persistent storage.
- The scene can be displayed in the browser.

At least one representative real-world environment must be reconstructed successfully.

### Dependencies

Phases 2 and 4.

Phase 5 may proceed independently of the scene reconstruction implementation.

---

# PHASE 7. 3D Viewer and Result Management

Priority: P0

### Objective

Implement the complete 3D result visualization experience.

Both generated objects and reconstructed scenes must be viewable through a unified interface.

### Tasks

**7.1. Three.js Integration**

Implement:

- React Three Fiber.
- Three.js Canvas.
- GLTFLoader.
- Camera configuration.
- Lighting.
- Background.
- Responsive viewport.

**7.2. Model Loading**

Implement:

- Authorized GLB retrieval.
- Blob URL handling.
- Loading indicators.
- Parsing error handling.
- Resource cleanup.

**7.3. Viewer Controls**

Implement:

- OrbitControls.
- Zoom.
- Pan.
- Reset camera.
- Fit to view.
- Grid toggle.
- Fullscreen mode.

**7.4. Model Information**

Display:

- Project name.
- Generation type.
- File format.
- File size.
- Creation date.
- Number of meshes where available.

**7.5. Download**

Implement authorized GLB downloading.

**7.6. Result Management**

Implement:

- Current result retrieval.
- Previous result preservation.
- Result metadata display.
- Handling of projects without a completed result.

**7.7. Performance**

Test:

- Individual objects.
- Medium-sized scenes.
- Large reconstructed scenes.

Optimize only where necessary.

### Deliverables

- Unified 3D viewer.
- GLB loader.
- Viewer toolbar.
- Camera controls.
- Result metadata panel.
- Download functionality.
- Viewer tests.

### Acceptance Criteria

- TripoSR models load successfully.
- COLMAP/OpenMVS scenes load successfully.
- Materials and textures are visible.
- Camera controls work correctly.
- Downloaded assets match stored results.
- Invalid GLB assets produce clear error messages.
- Resources are released when changing projects.

### Dependencies

Phases 3, 5 and 6.

Viewer development may begin earlier using clearly identified test fixtures, but final acceptance requires real generated results.

---

# PHASE 8. Reliability, Security and Optimization

Priority: P0

### Objective

Improve system reliability and ensure that the MVP can handle normal user workloads and expected failures.

### Tasks

**8.1. Authentication Security**

- Verify session expiration.
- Verify session revocation.
- Verify CSRF protection.
- Review cookie configuration.
- Review authorization dependencies.

**8.2. File Security**

- Verify file validation.
- Review storage key handling.
- Test path traversal protection.
- Restrict filesystem access.
- Test access to unauthorized assets.

**8.3. Generation Reliability**

- Test interrupted workers.
- Test task retries.
- Test duplicate task delivery.
- Test GPU failures.
- Test insufficient RAM.
- Test storage failures.
- Verify stale task recovery.

**8.4. Data Consistency**

- Verify Outbox recovery.
- Verify task and project status consistency.
- Verify generation result replacement.
- Verify previous result preservation.
- Verify cleanup operations.

**8.5. Resource Management**

- Configure worker concurrency.
- Configure processing timeouts.
- Monitor temporary storage usage.
- Verify cleanup of intermediate files.
- Verify GPU memory recovery.

**8.6. Performance Optimization**

Evaluate:

- API response time.
- Image upload throughput.
- TripoSR inference performance.
- COLMAP reconstruction time.
- OpenMVS processing performance.
- GLB loading time.
- Browser memory consumption.

**8.7. Infrastructure Reliability**

Test:

- Container restart.
- Redis restart.
- PostgreSQL restart.
- Worker restart.
- Storage persistence.
- Backup and restoration.

**8.8. Reliability and Security Regression Scenarios**

Test:

- CSRF token rotation and session binding.
- Worker termination during processing.
- Project deletion during active generation.
- Redis interruption after PostgreSQL commit.
- Duplicate delivery after dispatcher interruption.
- Database failure during result registration.

### Deliverables

- Security fixes.
- Reliability improvements.
- Task recovery procedures.
- Performance baseline.
- Improved error handling.
- Storage cleanup verification.
- Backup documentation.

### Acceptance Criteria

- Critical authorization tests pass.
- Worker failures do not permanently corrupt project state.
- Previous successful results remain accessible.
- Background tasks can recover from supported interruptions.
- Persistent data survives container restarts.
- No critical uncontrolled storage growth remains.
- Security-sensitive operations are adequately tested.

### Dependencies

Phases 2–7.

---

# PHASE 9. Comprehensive Testing and Quality Assurance

Priority: P0

### Objective

Execute the complete testing strategy and validate the system against all mandatory acceptance criteria.

### Tasks

**9.1. Frontend Tests**

Run:

- Unit tests.
- Component tests.
- API interaction tests.
- Viewer tests.
- Type checking.
- Linting.

**9.2. Backend Tests**

Run:

- Unit tests.
- API tests.
- Database tests.
- Authorization tests.
- Storage tests.
- Celery tests.
- Outbox tests.

**9.3. ML Integration Tests**

Run:

- Real TripoSR inference.
- Real COLMAP processing.
- Real OpenMVS processing.
- GLB validation.
- Processing performance tests.

**9.4. End-to-End Tests**

Verify the complete user workflows:

- Registration.
- Login.
- Project creation.
- Object image upload.
- Scene image upload.
- Object generation.
- Scene reconstruction.
- Processing status.
- Result visualization.
- Model download.
- Failed generation.
- Retry.
- Failed regeneration with previous result preservation.
- Project deletion during active processing.
- Recovery after worker interruption.
- Project deletion.

**9.5. Security Testing**

Verify:

- Authentication.
- Authorization.
- CSRF protection.
- File upload validation.
- User isolation.
- Private asset access.

**9.6. Performance Testing**

Establish baseline measurements for:

- Small object generation.
- Larger object generation.
- Small scene reconstruction.
- Complex scene reconstruction.
- GLB loading.

**9.7. Final Bug Fixes**

Resolve:

- Critical functional errors.
- Data consistency problems.
- Broken user workflows.
- Failed integrations.
- Invalid generated assets.
- Critical security issues.

### Deliverables

- Full test report.
- Code coverage report.
- ML processing report.
- Reconstruction quality report.
- Performance measurements.
- List of known limitations.
- Release readiness assessment.

### Acceptance Criteria

- All mandatory automated tests pass.
- Both real ML pipelines have been executed successfully.
- Both workflows have passed end-to-end validation.
- Generated GLB files pass validation.
- All mandatory product acceptance criteria are satisfied.
- No known unresolved critical defects remain.

### Dependencies

Phases 2–8.

---

# PHASE 10. MVP Release and Documentation

Priority: P0

### Objective

Prepare the application for its first complete MVP release.

### Tasks

**10.1. Release Configuration**

Prepare:

- Production environment configuration.
- Production Docker images.
- Persistent volumes.
- Database migrations.
- Reverse proxy.
- HTTPS configuration.
- Secure cookie configuration.
- Logging configuration.

**10.2. Deployment Verification**

Verify:

- Full application startup.
- User registration and login.
- Project creation.
- Image upload.
- Object generation.
- Scene reconstruction.
- Result viewing.
- Result downloading.

**10.3. Backup Procedures**

Document:

- Database backup.
- File storage backup.
- Database restoration.
- File storage restoration.
- Task recovery.

**10.4. User Documentation**

Provide instructions for:

- Registration.
- Project creation.
- Preparing object photographs.
- Preparing scene photographs.
- Starting generation.
- Viewing results.
- Downloading GLB files.

**10.5. Developer Documentation**

Update:

- README.
- Architecture diagrams.
- API documentation.
- Environment configuration.
- Docker Compose commands.
- ML worker setup.
- Testing instructions.

**10.6. Release**

Create a versioned MVP release.

Record:

- Application version.
- Database migration version.
- TripoSR revision.
- TripoSR model checkpoint revision.
- COLMAP version.
- OpenMVS version.
- Docker image identifiers.

### Deliverables

- Complete working MVP.
- Production Docker configuration.
- User documentation.
- Developer documentation.
- Deployment instructions.
- Release notes.
- Backup and recovery procedures.

### Acceptance Criteria

The MVP can be deployed and provides the following functionality:

1. User registration and authentication.
2. Project creation and management.
3. Uploading photographs.
4. Generating 3D objects using TripoSR.
5. Reconstructing scenes using COLMAP and OpenMVS.
6. Tracking asynchronous generation tasks.
7. Viewing 3D objects and scenes in a browser.
8. Downloading GLB assets.
9. Handling failed generation tasks.
10. Preserving user projects and generated assets.

---

## 6. Dependency Matrix

The following matrix describes the main dependencies between development phases.

| Phase | Depends On | Can Be Developed in Parallel |
|---|---|---|
| 0. Specification Consolidation | None | No |
| 1. Infrastructure | 0 | No |
| 2. Backend Foundation | 1 | No |
| 3. Frontend Integration | 2 | Partially with backend |
| 4. Background Processing | 2 | With Phase 3 |
| 5. Object Generation | 2, 4 | With Phase 6 |
| 6. Scene Reconstruction | 2, 4 | With Phase 5 |
| 7. 3D Viewer | 3, 5, 6 | Partially with ML work |
| 8. Reliability | 2–7 | Continuous |
| 9. QA | 2–8 | Continuous |
| 10. MVP Release | 9 | No |

### 6.1. Parallel Development

The following development activities may be performed independently after their shared dependencies are established:

**Frontend and Backend**

Frontend and backend developers can work in parallel using the canonical API contracts.

**Object Generation and Scene Reconstruction**

TripoSR and COLMAP/OpenMVS can be implemented independently because they use separate workers and processing interfaces.

**Infrastructure and Application Development**

Docker configuration and infrastructure automation can be developed alongside backend and ML implementation.

**Testing**

Unit and integration tests should be developed continuously rather than being postponed until the end.

### 6.2. Integration Dependencies

Despite parallel development, the following integrations require specific prerequisites:

- Frontend/backend integration requires stable API contracts.
- Celery integration requires persistent generation task models.
- Object Worker integration requires a working standalone TripoSR pipeline.
- Scene Worker integration requires a working standalone COLMAP/OpenMVS pipeline.
- Final viewer validation requires real generated GLB assets.

---

## 7. Major Milestones

Use milestones to track actual application readiness.

| Milestone | Expected Result |
|---|---|
| M0 — Architecture Ready | Specifications and contracts are consistent |
| M1 — Infrastructure Ready | Application services run through Docker Compose |
| M2 — Backend Ready | Authentication, projects and uploads work |
| M3 — Frontend Ready | Main user workflows are connected to the backend |
| M4 — Processing Ready | Background task architecture works |
| M5 — Object Generation Ready | TripoSR generates real 3D objects |
| M6 — Scene Reconstruction Ready | COLMAP/OpenMVS generates real scenes |
| M7 — Visualization Ready | Both asset types load in Three.js |
| M8 — Quality Ready | Reliability and testing criteria pass |
| M9 — MVP Released | Complete application is deployable |

A milestone is achieved only when its acceptance criteria are verified.

Do not mark a milestone complete merely because its implementation has been started.

---

## 8. Development Workflow for AI Coding Agents

### 8.1. General Instructions

The AI coding agent must treat the specification set as the source of truth for implementation.

Before modifying code:

1. Inspect the repository structure.
2. Read `00_project_overview.md`.
3. Read the relevant subsystem specifications.
4. Read related architecture documents.
5. Identify existing implementation.
6. Identify unmet requirements.
7. Prepare a concise implementation plan.

### 8.2. Phase-Based Execution

The agent must work on one development phase at a time unless explicit parallel development has been requested.

For each phase:

1. Identify all required tasks.
2. Determine implementation dependencies.
3. Implement functionality incrementally.
4. Add or update automated tests.
5. Run relevant tests.
6. Fix discovered problems.
7. Update documentation.
8. Provide a completion report.

Do not automatically move to subsequent phases when mandatory acceptance criteria remain unmet.

### 8.3. Implementation Constraints

The agent must:

- Follow the established technology stack.
- Preserve separation of responsibilities.
- Avoid unnecessary abstractions.
- Avoid monolithic files.
- Avoid duplicated business logic.
- Use typed interfaces.
- Follow API contracts.
- Use database migrations.
- Use persistent storage for generated assets.
- Keep processing asynchronous.
- Handle errors explicitly.
- Avoid fake production functionality.

### 8.4. Existing Code Protection

Before editing existing modules:

- Inspect current implementation.
- Check existing tests.
- Preserve working functionality.
- Avoid unrelated changes.
- Avoid deleting existing configuration without justification.

Do not rewrite the entire repository to implement a small isolated feature.

### 8.5. Dependency Changes

When adding or changing dependencies:

- Explain why the dependency is required.
- Check compatibility with the existing environment.
- Update the appropriate dependency file.
- Pin versions where reproducibility requires it.
- Document significant compatibility implications.

### 8.6. Architectural Changes

If a requirement cannot be implemented as specified:

1. Identify the blocking issue.
2. Explain the technical reason.
3. Describe the proposed alternative.
4. Identify affected specifications.
5. Update the architecture documentation.
6. Verify that related components remain compatible.

Do not silently replace the selected technologies or processing algorithms.

### 8.7. Testing Rules

Never claim a feature has been tested when the corresponding test was not executed.

Distinguish:

- Implemented.
- Tested successfully.
- Partially tested.
- Not tested.
- Blocked by unavailable dependencies.

Mocks must never be presented as proof of real ML integration.

### 8.8. Completion Report

After each implementation phase, provide a report using the following structure:

```text
IMPLEMENTATION REPORT

Phase:
Status:

1. Implemented Features
- ...

2. Modified Files
- ...

3. Added Dependencies
- ...

4. Tests Executed
- ...

5. Test Results
- ...

6. Known Issues
- ...

7. Unimplemented Requirements
- ...

8. Next Phase
- ...
```

The completion report must distinguish verified functionality from incomplete or untested functionality.

---

## 9. Risk Register

The following risks must be considered during implementation.

| Risk | Impact | Mitigation |
|---|---|---|
| Insufficient GPU VRAM | Object generation failure | Conservative worker concurrency and configurable chunk size |
| TripoSR reconstruction limitations | Inaccurate unseen geometry | Clear user guidance and representative quality tests |
| COLMAP feature matching failure | Incomplete scene reconstruction | Capture guidelines and reconstruction diagnostics |
| OpenMVS memory consumption | Worker failure | Resource limits and optional scalable processing |
| Large GLB files | Slow viewer loading | Measure asset complexity and optimize where needed |
| ML dependency conflicts | Unstable worker images | Independent worker environments and pinned versions |
| Worker interruption | Stuck processing tasks | Heartbeats, recovery and task idempotency |
| Redis interruption | Unpublished background tasks | Transactional Outbox |
| File storage growth | Disk exhaustion | Cleanup jobs and retention policies |
| OpenMVS license obligations | Deployment restrictions | Legal review before public or commercial release |
| Inaccurate API contracts | Frontend/backend integration errors | Canonical API contract document |
| Insufficient reconstruction datasets | Unreliable quality evaluation | Maintain fixed representative image datasets |

### 9.1. Technical Validation Priorities

Some uncertainties must be resolved early:

- Verify TripoSR inference on the intended development GPU.
- Verify compatibility of the chosen PyTorch and CUDA versions.
- Verify TripoSR GLB export, vertex colors and texture behavior on real data.
- Verify COLMAP CLI commands and CUDA configuration for the pinned version.
- Verify the OpenMVS build, native dependencies and GLB export availability.
- Verify that the GLB exported by OpenMVS loads in Three.js.
- Verify the selected OpenMVS build supports the intended GLB export.
- Verify actual processing times using representative input datasets.
- Verify that large scene assets remain usable in the browser.
- Verify Docker GPU container compatibility with the target host.
- Review OpenMVS licensing before distributing or operating the service publicly.

Do not postpone technical feasibility checks until the end of the roadmap.

---

## 10. MVP Definition of Done

The MVP is considered complete when all of the following conditions are satisfied.

### 10.1. Application

- Frontend is operational.
- Backend API is operational.
- Authentication works.
- Project management works.
- Image uploading works.

### 10.2. Object Generation

- TripoSR is integrated.
- Real image-to-3D inference works.
- Mesh extraction works.
- GLB export works.
- Results persist in storage.

### 10.3. Scene Reconstruction

- COLMAP integration works.
- Sparse reconstruction works.
- Camera estimation works.
- OpenMVS integration works.
- Dense reconstruction works.
- Mesh generation works.
- Texture generation works.
- GLB export works.

### 10.4. Processing Infrastructure

- Celery workers are operational.
- Redis is operational.
- Transactional Outbox is operational.
- Tasks are tracked in PostgreSQL.
- Failed tasks are handled correctly.
- Worker interruption recovery is supported.

### 10.5. Visualization

- Three.js loads generated assets.
- Individual objects are displayed.
- Reconstructed scenes are displayed.
- Camera controls work.
- GLB download works.

### 10.6. Reliability

- Projects are isolated by ownership.
- Source photographs persist.
- Generated assets persist.
- Previous successful results are preserved.
- Cleanup operations are recoverable.
- Docker Compose deployment works.

### 10.7. Quality

- Required unit tests pass.
- Required integration tests pass.
- Main E2E workflows pass.
- Real ML integration tests pass.
- Generated assets pass validation.
- No known unresolved critical defects remain.

---

## 11. Future Development

After the MVP is complete, the application may be extended.

### 11.1. Improved Object Generation

Potential improvements:

- Multiple-image object reconstruction.
- Alternative image-to-3D models.
- Improved geometry refinement.
- Texture quality improvements.
- Mesh decimation.
- Automatic object orientation.
- Improved background removal.

### 11.2. Improved Scene Reconstruction

Potential improvements:

- More advanced COLMAP matching strategies — implemented as an opt-in ALIKED + LightGlue backend with COLMAP SIFT as the default/fallback (see `docs/additions/12_advanced_feature_matching.md` and `docs/reviews/increment12_closeout.md`); neural mode is not the default because the current single-scene benchmark shows no quality improvement.
- Automatic image quality evaluation — implemented as an advisory shared analyzer in `ml/image_quality/` (see `docs/additions/11_image_quality_analysis.md`); it reports findings and perceptual near-duplicates without rejecting or removing photographs.
- Automatic camera trajectory visualization.
- Reconstruction component merging.
- Large-scene processing.
- Automatic scene alignment.
- Metric scale estimation.
- Better treatment of low-texture surfaces.

### 11.3. Neural Scene Reconstruction

Potential technologies:

- 3D Gaussian Splatting.
- NeRF.
- Hybrid mesh and Gaussian representations.

These technologies may improve visualization and reconstruction quality but should be evaluated separately from the initial photogrammetry pipeline.

### 11.4. Advanced 3D Editing

Potential functionality:

- Semantic segmentation.
- Independent object extraction.
- Scene object manipulation.
- Geometry editing.
- Texture editing.
- Scene composition.
- Export to additional 3D formats.

These features are outside the MVP.

### 11.5. Infrastructure Evolution

Potential improvements:

- S3-compatible object storage.
- Dedicated GPU server.
- Distributed workers.
- Kubernetes.
- Advanced metrics and monitoring.
- Automated deployment pipeline.

---

## 12. Related Specifications

This document defines the overall implementation roadmap.

It references all previous project specifications:

- `00_project_overview.md`
- `01_product_requirements.md`
- `02_ui_ux_specification.md`
- `03_frontend_specification.md`
- `04_backend_specification.md`
- `05_database_specification.md`
- `06_object_generation.md`
- `07_scene_reconstruction.md`
- `08_infrastructure.md`
- `09_testing.md`
- `AI_DEVELOPMENT_GUIDE.md` — development workflow and agent rules that govern how each phase is executed.

Supporting architecture documents:

- `architecture/system_architecture.md`
- `architecture/api_contracts.md`
- `architecture/data_flow.md`

All implementation work must remain consistent with the project specifications and the phase dependencies defined in this roadmap.