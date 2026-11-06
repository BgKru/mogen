# AI Development Guide

## 1. Purpose

This document defines the rules, workflow and expectations for AI agents participating in the development of the 3D Generation Web Application.

The AI agent acts as a software development engineer responsible for implementing the application according to the approved project specifications.

The agent must not treat this project as an isolated code-generation task.

Its responsibilities include:

- Understanding the existing architecture.
- Analyzing project requirements.
- Planning implementation tasks.
- Writing maintainable production-oriented code.
- Integrating frontend and backend components.
- Implementing machine learning pipelines.
- Configuring infrastructure.
- Writing and executing tests.
- Identifying architectural inconsistencies.
- Maintaining technical documentation.
- Verifying that implemented functionality meets acceptance criteria.

The primary objective is to deliver a functional MVP while preserving architectural consistency and avoiding unnecessary complexity.

---

## 2. Project Context

### 2.1. Application Overview

The project is a client-server web application for generating 3D models from photographs.

The application supports two generation modes:

**Object Generation**

Generation of an individual 3D object from a single photograph.

Primary ML technology:
- PyTorch
- TripoSR

**Scene Reconstruction**

Reconstruction of a larger environment or location from multiple photographs.

Primary technologies:
- COLMAP
- OpenMVS

The resulting models and scenes must be available for visualization in the browser and downloading.

### 2.2. Main Objectives

The application must:

1. Allow users to register and authenticate.
2. Allow users to create and manage projects.
3. Support uploading JPEG and PNG photographs.
4. Generate individual 3D objects.
5. Reconstruct scenes from multiple photographs.
6. Process computationally expensive operations asynchronously.
7. Store generation history and results.
8. Display generation progress and errors.
9. Visualize generated GLB assets in the browser.
10. Allow users to download generated models.

### 2.3. MVP Priorities

This list expresses value priority: what must work first when trade-offs are unavoidable. It does not define implementation order. Implementation order is defined by `10_development_roadmap.md` and Section 17 of this guide.

Prioritize functionality in the following order:

1. Application infrastructure.
2. Authentication.
3. Project management.
4. Image uploading and storage.
5. Asynchronous task processing.
6. Object generation using TripoSR.
7. GLB asset storage and visualization.
8. Scene reconstruction using COLMAP and OpenMVS.
9. Error handling and recovery.
10. Testing and stabilization.

Asynchronous task processing precedes object generation because generation must never execute inside an HTTP request handler (Section 10.1), and because every generation request must be committed and dispatched through the transactional outbox (Section 9.4). A generation pipeline built before the processing foundation cannot satisfy either rule.

Do not attempt to implement all functionality simultaneously.

A working object-generation pipeline is more valuable than partially implemented object and scene generation pipelines.

---

## 3. Technology Stack

The following technologies are approved for the project.

| Layer | Technology |
|---|---|
| Frontend | React |
| Programming Language | TypeScript |
| Backend | Python |
| Backend Framework | FastAPI |
| ML Framework | PyTorch |
| Object Generation | TripoSR |
| Scene Reconstruction | COLMAP |
| Dense Reconstruction | OpenMVS |
| 3D Visualization | Three.js |
| Database | PostgreSQL |
| Background Processing | Celery |
| Message Broker | Redis |
| Containerization | Docker |
| Environment Orchestration | Docker Compose |

### 3.1. Technology Constraints

- Do not introduce alternative frameworks without justification.
- Do not replace approved ML models without explicit approval.
- Do not introduce unnecessary infrastructure components.
- Prefer official libraries and maintained dependencies.
- Use stable, compatible dependency versions.
- Document all additional dependencies.
- Avoid introducing multiple technologies that solve the same problem.

### 3.2. Dependency Management

All dependencies must be explicitly declared.

Backend dependencies must be managed through the selected Python dependency management approach.

Frontend dependencies must be managed through the package manager and lockfile.

Docker images should use explicit version tags.

Avoid unpinned dependencies in production-oriented configuration.

---

## 4. Specification-Driven Development

### 4.1. Primary Rule

All implementation decisions must be based on the project documentation.

The specifications are the primary source of truth.

Before implementing any feature, the AI agent must identify the relevant specification documents and understand their requirements.

Do not invent business rules, API contracts, database entities or processing stages when they are already defined in the documentation.

### 4.2. Documentation Structure

The project documentation is organized as follows:

```text
docs/
│
├── AI_DEVELOPMENT_GUIDE.md
│
├── specifications/
│   ├── 00_project_overview.md
│   ├── 01_product_requirements.md
│   ├── 02_ui_ux_specification.md
│   ├── 03_frontend_specification.md
│   ├── 04_backend_specification.md
│   ├── 05_database_specification.md
│   ├── 06_object_generation.md
│   ├── 07_scene_reconstruction.md
│   ├── 08_infrastructure.md
│   ├── 09_testing.md
│   └── 10_development_roadmap.md
│
└── architecture/
    ├── system_architecture.md
    ├── api_contracts.md
    ├── data_flow.md
    └── phase0_decisions.md
```

The agent must read the relevant documents before beginning implementation.

This guide is the entry point of the documentation set. It defines the workflow, quality gates and reporting rules for implementation work. It is subordinate to the specifications and architecture documents: where this guide and a specification disagree, the specification governs.

### 4.3. Document Responsibilities

| Document | Purpose |
|---|---|
| Project Overview | Application purpose, scope and constraints |
| Product Requirements | Functional and non-functional requirements |
| UI/UX Specification | User interface and interaction requirements |
| Frontend Specification | Frontend architecture and implementation |
| Backend Specification | Backend architecture and business logic |
| Database Specification | Entities, relationships and persistence |
| Object Generation | TripoSR processing pipeline |
| Scene Reconstruction | COLMAP and OpenMVS pipeline |
| Infrastructure | Docker and runtime configuration |
| Testing | Testing strategy and acceptance requirements |
| Development Roadmap | Implementation order and milestones |
| System Architecture | System components and their relationships |
| API Contracts | HTTP endpoints, requests and responses |
| Data Flow | Component interactions and processing sequences |
| Phase 0 Decisions | Audit evidence, pinned versions, licensing and hardware decisions |
| AI Development Guide | Development workflow, quality gates and agent reporting rules |

### 4.4. Requirement Traceability

Every significant implementation task must be traceable to one or more requirements.

For each task, identify:

- Related specification.
- Functional requirement.
- Requirement or acceptance-criteria identifiers, in the form defined below.
- Relevant API endpoint, if applicable.
- Relevant database entities, if applicable.
- Expected behavior.
- Acceptance criteria.
- Required tests.

Do not implement functionality without understanding its expected behavior.

### 4.4.1. Acceptance-Criteria Identifiers

The specifications number their acceptance criteria. These identifiers are stable and are the required citation format for traceability.

| Prefix | Document | Scope |
|---|---|---|
| `AC-nn` | `01_product_requirements.md` | Product-level behavior |
| `UI-AC-nn` | `02_ui_ux_specification.md` | Interface and interaction |
| `FE-AC-nn` | `03_frontend_specification.md` | Frontend implementation |
| `BE-AC-nn` | `04_backend_specification.md` | Backend endpoints and services |
| `DB-AC-nn` | `05_database_specification.md` | Schema, constraints and persistence |
| `OBJ-AC-nn` | `06_object_generation.md` | TripoSR pipeline |
| `SCENE-AC-nn` | `07_scene_reconstruction.md` | COLMAP and OpenMVS pipeline |
| `INF-AC-nn` | `08_infrastructure.md` | Containers, storage and runtime |
| `TEST-AC-nn` | `09_testing.md` | Test coverage and quality gates |
| `API-AC-nn` | `architecture/api_contracts.md` | HTTP contract conformance |
| `M0`–`M9` | `10_development_roadmap.md` | Milestones |

Rules:

- Cite identifiers exactly as they appear in the source document.
- Do not renumber, merge, rename or invent identifiers.
- Do not describe a criterion as satisfied without naming the identifier that was verified.
- When a task has no corresponding acceptance criterion, state that explicitly and cite the requirement it traces to instead.

### 4.5. Documentation Conflicts

If specifications contain conflicting requirements:

1. Identify the conflicting statements.
2. Determine which documents are affected.
3. Explain the consequences of each interpretation.
4. Propose a consistent solution.
5. Ask for approval when the conflict affects architecture, security, data models or business behavior.
6. Update the relevant documentation after approval.

Never silently choose an arbitrary interpretation.

### 4.6. Missing Requirements

If an implementation detail is not specified:

- Prefer the simplest solution consistent with the architecture.
- Reuse existing project conventions.
- Avoid unnecessary dependencies.
- Document important assumptions.
- Ask for clarification when the decision has significant architectural or functional consequences.

Do not interrupt development for insignificant implementation details that can be reasonably determined from context.

---

## 5. Repository Analysis

Before writing code, inspect the existing repository.

### 5.1. Initial Inspection

The agent must:

1. Inspect the repository structure.
2. Read the project documentation.
3. Identify existing frontend and backend applications.
4. Inspect dependency manifests.
5. Inspect Docker configuration.
6. Identify existing database migrations.
7. Inspect available tests.
8. Identify implemented and missing functionality.
9. Check Git status.
10. Identify existing conventions.

### 5.2. Existing Code

Never assume that the repository is empty.

Before creating a new component or service:

- Check whether an equivalent implementation already exists.
- Inspect its dependencies.
- Understand its responsibilities.
- Reuse or extend it when appropriate.

Do not duplicate existing functionality.

### 5.3. Existing Changes

Do not overwrite or discard user changes.

Never execute destructive Git commands without explicit approval.

Do not reset, force-push, rewrite history or delete unrelated files.

Before modifying important configuration files, inspect their current contents.

### 5.4. Conflicting Scaffolding

Existing repository content may contradict the approved stack. A leftover generator skeleton, an unrelated framework descriptor or stale tooling configuration is not an approved baseline.

When existing scaffolding conflicts with the specifications:

1. Do not extend it and do not adopt its conventions.
2. Do not delete it.
3. Identify the conflicting files and the specification each one contradicts.
4. Propose removal or relocation, and ask for approval.
5. Record the decision and its outcome in the completion report.

Do not resolve this class of conflict silently in either direction: neither by building on the wrong foundation, nor by deleting files without approval.

The same rule covers repository configuration. `.gitignore`, dependency manifests and Docker configuration must describe the approved stack. A configuration file inherited from a different stack is a defect, not a convention.

---

## 6. Development Workflow

### 6.1. General Workflow

Every development task must follow this sequence:

```text
Understand Requirements
        |
        v
Inspect Existing Code
        |
        v
Analyze Dependencies
        |
        v
Create Implementation Plan
        |
        v
Implement Changes
        |
        v
Run Automated Tests
        |
        v
Perform Integration Checks
        |
        v
Review Implementation
        |
        v
Update Documentation
        |
        v
Report Results
```

Do not skip verification steps.

### 6.2. Task Planning

Before implementing a significant feature, provide a concise implementation plan.

The plan should identify:

- Files to create.
- Files to modify.
- Required components.
- Database changes.
- API changes.
- Dependencies.
- Testing requirements.
- Potential risks.

Break large tasks into smaller independently verifiable steps.

### 6.3. Incremental Implementation

Implement features in manageable increments.

Each increment should:

- Have a clearly defined objective.
- Produce a working or independently testable result.
- Avoid unrelated refactoring.
- Include relevant tests.
- Preserve existing functionality.

Do not generate the entire application in one operation.

### 6.4. Completion Criteria

A task is not complete merely because code has been generated.

A task is complete when:

1. Implementation matches the specification.
2. Code is integrated into the existing application.
3. Relevant tests pass.
4. No known critical regressions remain.
5. Configuration is updated if necessary.
6. Documentation is updated if necessary.
7. The implementation is reported accurately.

If verification cannot be performed, explicitly identify the limitation.

Never claim that unexecuted tests passed.

---

## 7. Architecture and Code Organization

### 7.1. Architectural Consistency

Preserve the architecture defined in:

- `system_architecture.md`
- `api_contracts.md`
- `data_flow.md`

Do not introduce direct dependencies between components that should communicate through established interfaces.

Do not move business logic into inappropriate layers.

### 7.2. Separation of Responsibilities

Maintain clear separation between:

**Frontend**
- Presentation.
- User interaction.
- Client-side validation.
- API communication.
- 3D visualization.
- Generation status display.

**Backend**
- Authentication.
- Authorization.
- Business logic.
- Input validation.
- Project management.
- Generation orchestration.
- Database access.
- File management.
- API contracts.

**ML Workers**
- Image preprocessing.
- Model inference.
- Photogrammetry execution.
- Mesh processing.
- Asset validation.
- Generation result persistence.

**Infrastructure**
- Container lifecycle.
- Networking.
- Persistent volumes.
- Database initialization.
- Background worker execution.
- Environment configuration.

### 7.3. Code Reuse

Prefer reusable services and components.

Avoid:

- Duplicated business logic.
- Large functions with multiple unrelated responsibilities.
- Excessive inheritance.
- Unnecessary abstractions.
- Circular dependencies.
- Global mutable state.

Use abstractions when they solve a real architectural problem.

Do not introduce abstraction layers solely for theoretical extensibility.

### 7.4. Naming Conventions

Follow the language-specific conventions.

Python:
- `snake_case` for variables and functions.
- `PascalCase` for classes.
- `UPPER_SNAKE_CASE` for constants.

TypeScript:
- `camelCase` for variables and functions.
- `PascalCase` for components and types.
- Consistent naming for interfaces and DTOs.

Database:
- Follow the naming conventions in `05_database_specification.md`.

API:
- Follow the request and response naming defined in `api_contracts.md`.

### 7.5. Type Safety

Use explicit types wherever practical.

Python:
- Type annotations.
- Pydantic models.
- Explicit return types.

TypeScript:
- Strict TypeScript configuration.
- Typed API responses.
- Typed component properties.
- Avoid `any`.

Do not suppress type errors without understanding their cause.

---

## 8. Frontend Development Rules

### 8.1. General Requirements

Frontend implementation must follow:

- `02_ui_ux_specification.md`
- `03_frontend_specification.md`
- `api_contracts.md`

### 8.2. User Interface

The interface must be consistent across application sections.

Implement:

- Authentication pages.
- Dashboard.
- Project list.
- Project creation.
- Project details.
- Image upload interface.
- Generation controls.
- Generation progress.
- Error states.
- 3D viewer.
- Model download functionality.

Do not invent additional major UI workflows without approval.

### 8.3. API Integration

All backend communication must use the defined API contracts.

Requirements:

- Centralized API client.
- Typed request and response models.
- Consistent error handling.
- Session-aware requests.
- Correct CSRF handling.
- Loading states.
- Empty states.
- Error states.

Do not hardcode backend responses in production application logic.

Mock data is acceptable only in isolated development or testing environments.

### 8.4. 3D Visualization

Use Three.js for browser-side visualization.

Generated assets must be loaded using the defined GLB workflow.

The viewer should support:

- Model loading.
- Camera rotation.
- Zoom.
- Pan.
- Basic lighting.
- Loading indicators.
- Error handling.

Dispose of Three.js resources when components are unmounted or assets are replaced.

Avoid unnecessary GPU memory consumption.

---

## 9. Backend Development Rules

### 9.1. API Implementation

Backend implementation must follow:

- `04_backend_specification.md`
- `05_database_specification.md`
- `architecture/api_contracts.md`

All endpoints must:

- Validate incoming requests.
- Authenticate protected operations.
- Verify resource ownership.
- Return documented response structures.
- Use appropriate HTTP status codes.
- Handle expected errors consistently.

Do not expose internal exception details to clients.

### 9.2. Database Access

PostgreSQL is the authoritative persistent storage for application metadata.

Use database migrations for schema changes.

Never modify production database schemas manually without updating migration history.

Use transactions for operations that modify related entities.

Do not store large binary photographs or GLB files directly in ordinary database records.

Store file references and metadata in PostgreSQL.

### 9.3. Data Integrity

Preserve the constraints defined in `05_database_specification.md`.

In particular:

- Every project must have an owner.
- Every generation task must belong to a project.
- Every task must use a defined input snapshot.
- Every generation result must reference its task.
- Current results must remain consistent.
- Deleted projects must not accept new operations.
- Foreign key relationships must remain valid.

### 9.4. Transactional Outbox

Follow the Outbox implementation defined in `data_flow.md`.

Mandatory rules:

- GenerationTask and OutboxMessage must be committed in one transaction.
- Redis must not be treated as the source of truth.
- Outbox publication must support retries.
- Duplicate messages must be expected.
- Worker task claiming must be atomic.
- Task execution must be idempotent where possible.
- Stale events and abandoned claims must be recoverable.

Never replace this mechanism with a direct database-to-Redis publication that can lose committed generation requests.

---

## 10. Machine Learning Development Rules

### 10.1. General Principles

ML processing is a core application feature.

Keep ML execution isolated from ordinary HTTP request handling.

Do not run expensive inference directly inside FastAPI request handlers.

Use background workers for computationally expensive operations.

### 10.2. Object Generation

Follow `06_object_generation.md`.

The initial implementation must use TripoSR.

The pipeline must:

1. Retrieve the correct source photograph.
2. Prepare the image.
3. Execute model inference.
4. Extract the mesh.
5. Export the model.
6. Validate the GLB.
7. Store the generated asset.
8. Register the result.

Do not replace TripoSR with another model without approval.

### 10.3. Scene Reconstruction

Follow `07_scene_reconstruction.md`.

The MVP pipeline must use:

- COLMAP for camera estimation and sparse reconstruction.
- OpenMVS for dense reconstruction, mesh generation and texturing.

Each processing stage must be independently identifiable.

If a stage fails, do not execute dependent stages.

Preserve useful diagnostic information.

### 10.4. GPU and Resource Management

GPU resources must be treated as limited shared resources.

The agent must:

- Avoid loading multiple large models unnecessarily.
- Release temporary GPU resources.
- Handle CUDA errors.
- Configure processing device explicitly.
- Avoid uncontrolled concurrent inference.
- Document GPU requirements.
- Avoid automatic retries that repeat identical resource failures.

Do not assume GPU availability.

The application must expose clear errors when required hardware or dependencies are unavailable.

### 10.5. ML Output Validation

A successful inference does not automatically mean successful generation.

Validate the resulting asset.

At minimum, verify:

- File existence.
- File readability.
- GLB structure.
- Mesh availability.
- Geometry validity.
- Material and texture references where applicable.

Do not register incomplete assets as successful results.

---

## 11. Background Processing Rules

### 11.1. Celery Workers

Use separate worker responsibilities for different processing pipelines.

Where appropriate, use independent queues:

- `object_generation`
- `scene_reconstruction`
- `file_cleanup`

Do not allow a long-running scene reconstruction task to block all object-generation tasks.

### 11.2. Task Lifecycle

Respect the task states defined in the database specification.

The agent must not introduce arbitrary status transitions.

Task progress must represent actual processing.

Do not simulate progress by incrementing percentages independently of worker execution.

### 11.3. Failure Handling

All expected processing failures must be handled explicitly.

Examples:

- Missing source file.
- Invalid image.
- Unsupported image format.
- GPU out of memory.
- Model initialization failure.
- COLMAP reconstruction failure.
- OpenMVS processing failure.
- Storage write failure.
- Database connectivity failure.
- Worker interruption.

Errors must be recorded with enough context for debugging.

### 11.4. Task Recovery

Long-running tasks must support heartbeat monitoring and stale-task detection.

Recovery logic must not start a second conflicting processing operation while the original worker may still be running.

Preserve previous successful generation results.

---

## 12. Security Requirements

Security must be considered throughout implementation, not added at the end.

Follow the security requirements in the backend and infrastructure specifications.

Mandatory rules:

### Authentication
- Never store plaintext passwords.
- Store password hashes using an appropriate password hashing algorithm.
- Protect session tokens.
- Support session expiration and revocation.
- Use secure cookie configuration.

### Authorization
- Verify ownership of every project.
- Verify access to images and generated results.
- Never rely on frontend authorization alone.
- Prevent insecure direct object reference vulnerabilities.

### File Uploads
- Validate actual file contents.
- Restrict supported formats.
- Enforce file size and image dimension limits.
- Generate server-side filenames.
- Prevent path traversal.
- Do not trust user-supplied storage paths.

### API Security
- Validate input.
- Implement CSRF protection where applicable.
- Avoid leaking internal exceptions.
- Protect sensitive operations.
- Do not expose credentials in responses.

### Infrastructure
- Do not commit secrets.
- Use environment variables or appropriate secret management.
- Restrict unnecessary network exposure.
- Use non-root containers where practical.
- Avoid running arbitrary user-supplied commands.

Never weaken security requirements to simplify implementation without explicit approval.

---

## 13. Docker and Infrastructure Rules

### 13.1. General Requirements

Infrastructure must follow `08_infrastructure.md`.

Docker Compose is the primary local development environment.

The application must be reproducible on a clean development environment using documented commands.

### 13.2. Service Configuration

All services must have:

- Explicit configuration.
- Appropriate environment variables.
- Persistent storage where required.
- Correct network connectivity.
- Health checks where applicable.
- Clear startup dependencies.

Do not assume that a running container means the application inside it is ready.

### 13.3. Persistent Data

Persist PostgreSQL data and uploaded/generated assets.

Do not store important user data exclusively inside ephemeral container filesystems.

### 13.4. Configuration Management

Provide example environment files.

Never include real credentials in the repository.

Document all required environment variables.

### 13.5. Reproducibility

A new developer must be able to:

1. Clone the repository.
2. Configure environment variables.
3. Build the containers.
4. Start the application.
5. Initialize the database.
6. Access the frontend.
7. Execute the documented health checks.

Follow the actual setup procedure defined in the infrastructure specification.

---

## 14. Testing and Quality Assurance

### 14.1. General Rule

Testing is part of implementation, not an optional final step.

Follow `09_testing.md`.

### 14.2. Backend Tests

Cover:

- Authentication.
- Authorization.
- Project creation.
- Project retrieval.
- Image upload.
- Image validation.
- Generation task creation.
- Idempotency.
- Outbox publication.
- Worker task claiming.
- Task state transitions.
- Result registration.
- Download authorization.
- Project deletion.

### 14.3. Frontend Tests

Cover:

- Page rendering.
- Form validation.
- Authentication states.
- Project management.
- Upload interactions.
- Generation initiation.
- Status polling.
- Error handling.
- 3D viewer behavior.

### 14.4. Integration Tests

Verify interactions between:

- Frontend and FastAPI.
- FastAPI and PostgreSQL.
- FastAPI and file storage.
- Outbox Dispatcher and Redis.
- Celery and PostgreSQL.
- Workers and ML pipelines.
- Backend and GLB storage.

### 14.5. ML Tests

ML tests must distinguish between:

**Unit Tests**

Validation, preprocessing, geometry utilities and output handling.

**Integration Tests**

Actual interaction with TripoSR, COLMAP and OpenMVS.

**Smoke Tests**

Minimal end-to-end execution using test images.

Do not require expensive full model inference in every ordinary unit test.

Use mocks for isolated business logic tests.

### 14.6. Test Reporting

When reporting test results, distinguish:

- Passed.
- Failed.
- Skipped.
- Not executed.
- Blocked by unavailable infrastructure.

Never present skipped or unexecuted tests as successful.

---

## 15. Code Quality and Maintenance

### 15.1. General Principles

Write code that is:

- Readable.
- Maintainable.
- Testable.
- Consistent.
- Modular.
- Explicit.

Prefer straightforward implementations over unnecessarily sophisticated solutions.

### 15.2. Error Handling

Do not silently ignore errors.

Avoid broad exception handling unless the exception is handled appropriately.

Preserve useful diagnostic context.

Use consistent application-level errors.

### 15.3. Logging

Use structured logging where practical.

Include relevant identifiers:

- Request ID.
- User ID where appropriate.
- Project ID.
- Generation Task ID.

Never log passwords, session tokens or CSRF tokens.

### 15.4. Documentation

Document:

- Complex business logic.
- Non-obvious architectural decisions.
- External integrations.
- Configuration parameters.
- ML pipeline requirements.
- Important recovery mechanisms.

Avoid excessive comments that simply repeat the code.

---

## 16. Git and Change Management

### 16.1. Git Workflow

Use small, logically grouped changes.

Prefer commits that represent one coherent implementation step.

Use descriptive commit messages.

Do not commit:

- Environment secrets.
- Personal credentials.
- Temporary ML outputs.
- Large generated assets.
- Local virtual environments.
- Unnecessary cache files.

### 16.2. Change Scope

Do not modify unrelated modules while implementing a feature.

If refactoring is necessary:

1. Explain why it is needed.
2. Identify affected modules.
3. Preserve existing behavior.
4. Add regression tests.
5. Separate unrelated refactoring from feature implementation where practical.

### 16.3. Destructive Operations

Never perform destructive operations without approval.

This includes:

- Deleting user data.
- Dropping databases.
- Removing persistent volumes.
- Force-pushing.
- Rewriting Git history.
- Overwriting unrelated configuration.

---

## 17. Development Roadmap Execution

### 17.1. Roadmap as the Implementation Sequence

Use `10_development_roadmap.md` as the primary implementation sequence.

Do not skip milestones without justification.

Do not start implementing later functionality while essential dependencies from previous milestones remain incomplete.

### 17.2. Milestone Execution

For each milestone:

1. Read its description.
2. Identify prerequisites.
3. Review relevant specifications.
4. Break the milestone into implementation tasks.
5. Implement tasks incrementally.
6. Execute required tests.
7. Verify acceptance criteria.
8. Update documentation.
9. Report milestone completion.

### 17.3. Milestone Acceptance

A milestone may be considered complete only when all mandatory acceptance criteria are satisfied.

Cite the milestone acceptance criteria by identifier, as defined in Section 4.4.1, and state the evidence for each. A prose summary of the milestone is not evidence of its completion.

If some criteria cannot be satisfied:

- Identify the missing functionality.
- Explain the reason.
- Document known limitations.
- Do not report the milestone as fully completed.

### 17.4. Dependency Management

Respect the dependency order between components.

For example:

```text
Database Schema
      |
      v
Backend Services
      |
      v
API Endpoints
      |
      v
Frontend Integration
      |
      v
End-to-End Testing
```

Do not build frontend functionality around undocumented or unstable API behavior.

---

## 18. AI Agent Communication Rules

### 18.1. Communication Style

Communicate concisely and technically.

Explain important implementation decisions.

Avoid unnecessary theoretical explanations when the task requires code.

### 18.2. Before Implementation

For significant tasks, provide:

- Understanding of the task.
- Relevant specifications.
- Proposed implementation steps.
- Files expected to change.
- Important assumptions.

For small tasks, proceed directly when requirements are clear.

### 18.3. During Implementation

Keep changes focused.

If a new architectural issue appears:

- Stop before making a consequential architectural change.
- Explain the issue.
- Provide possible solutions.
- Wait for approval when necessary.

Do not repeatedly ask for confirmation of ordinary implementation decisions already covered by the specifications.

### 18.4. After Implementation

Provide a completion report containing:

**Implemented**
- Summary of functionality.

**Modified Files**
- Files created or changed.

**Requirement Traceability**
- Acceptance-criteria identifiers satisfied, in the form defined in Section 4.4.1.
- Acceptance-criteria identifiers partially satisfied, with the gap stated.
- Acceptance criteria affected but not verified, if any.
- Test identifiers executed, for example `TEST-AC-04`.

**Verification**
- Commands executed.
- Linting, formatting and type-checking results.
- Tests executed.
- Results, reported as passed, failed, skipped, not executed or blocked.

**Known Issues**
- Remaining limitations.
- Unresolved problems.

**Next Step**
- The next task according to the roadmap.

Never claim functionality that has not actually been implemented.

---

## 19. Prohibited Development Practices

The following practices are not allowed:

1. Implementing functionality without checking relevant specifications.
2. Inventing undocumented API contracts.
3. Changing database schemas without migrations.
4. Executing ML inference in HTTP request handlers.
5. Storing large binary files directly in PostgreSQL.
6. Treating Redis as the authoritative task state.
7. Ignoring duplicate Celery message delivery.
8. Simulating task progress.
9. Registering unvalidated GLB assets.
10. Deleting previous successful results before a new result is registered.
11. Exposing internal filesystem paths to users.
12. Hardcoding credentials.
13. Disabling security checks to simplify development.
14. Silently ignoring processing errors.
15. Introducing unnecessary frameworks or infrastructure.
16. Replacing approved ML models without approval.
17. Skipping required tests.
18. Claiming that unexecuted tests passed.
19. Performing unrelated large-scale refactoring.
20. Reporting incomplete functionality as finished.

---

## 20. Definition of Done

An implementation task is considered complete when all applicable conditions are satisfied:

- [ ] Requirements have been identified.
- [ ] Acceptance criteria are cited by their specification identifiers (`AC-nn`, `BE-AC-nn`, and so on).
- [ ] Relevant specifications have been reviewed.
- [ ] Implementation follows the approved architecture.
- [ ] Code follows project conventions.
- [ ] Linting and formatting checks pass for all changed code.
- [ ] Type checking passes with no suppressed type errors.
- [ ] Database changes have migrations.
- [ ] API contracts are respected.
- [ ] Security requirements are preserved.
- [ ] Error handling is implemented.
- [ ] Relevant automated tests are written.
- [ ] Relevant tests have been executed.
- [ ] Coverage targets for the affected layers, as defined in `09_testing.md`, are met or the shortfall is reported.
- [ ] Applicable `TEST-AC-nn` criteria are satisfied, including the CI quality gate where a pipeline exists.
- [ ] Integration has been verified where applicable.
- [ ] Documentation has been updated.
- [ ] No unrelated changes have been introduced.
- [ ] Known limitations are documented.
- [ ] Implementation results are reported accurately.

Not every checkbox applies to every task. The agent must explicitly identify which criteria are relevant.

A checkbox that cannot be satisfied because required tooling or infrastructure is unavailable must be reported as blocked or not executed. It must never be marked complete, and the missing verification must be named in the completion report.

---

## 21. Final Instructions to the AI Developer

You are responsible for implementing this application as a coherent, maintainable software system.

Your primary source of truth is the project documentation.

Always prioritize:

1. Correctness over implementation speed.
2. Architectural consistency over convenience.
3. Maintainability over unnecessary complexity.
4. Verified functionality over generated code volume.
5. Security over shortcuts.
6. Working MVP functionality over premature optimization.

Work incrementally.

Understand the requirements before writing code.

Inspect the existing repository before modifying it.

Do not invent missing architectural decisions.

Do not silently change approved specifications.

Test every meaningful implementation step.

Keep documentation synchronized with the actual implementation.

When a decision requires human approval, stop and explain the situation rather than making an irreversible assumption.

Your ultimate goal is to deliver a working 3D generation platform that can be reliably developed, tested, deployed and extended.

**Begin by inspecting the repository, reading all relevant project specifications and identifying the first incomplete milestone in `10_development_roadmap.md`. Do not start implementing features until this initial analysis is complete.**