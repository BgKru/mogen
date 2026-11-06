# 01 — Product Requirements Specification

## 1. Document Purpose

This document defines the product requirements for the web-based 3D generation application.

It describes:
- Product goals and scope.
- User roles.
- Main user scenarios.
- Functional requirements.
- Non-functional requirements.
- MVP limitations.
- Acceptance criteria.

This specification defines WHAT the application must do, not HOW individual components must be implemented.

Technical implementation details are defined in the corresponding subsystem specifications.

---

## 2. Product Overview

### 2.1. Product Description

The product is a client-server web application that allows users to generate 3D models of individual objects and reconstruct entire 3D environments from photographs.

The application simplifies 3D content creation and reduces the time required for manual modeling.

Users interact with the application through a web interface.

The application supports two independent generation workflows:

1. Object Generation — generating an individual 3D model from a single photograph.
2. Scene Reconstruction — reconstructing a real environment from multiple photographs using photogrammetry.

### 2.2. Product Goals

The primary goals are:

- Provide an accessible interface for generating 3D content.
- Reduce the amount of manual 3D modeling required.
- Support reconstruction of individual objects and complete environments.
- Allow users to preview generated results directly in a browser.
- Provide downloadable 3D assets.
- Establish an extensible architecture for integrating additional reconstruction algorithms.

### 2.3. Product Differentiation

The application is inspired by Meshy AI and Tripo AI.

Its primary differentiator is support for full-scene reconstruction in addition to individual object generation.

Unlike generative scene creation, the MVP scene reconstruction workflow is based on photogrammetry. The resulting scene represents an approximation of the physical environment captured in the source photographs.

---

## 3. Target Users and Roles

### 3.1. Registered User

The primary application user.

A registered user can:

- Create and manage personal projects.
- Upload photographs.
- Generate 3D objects.
- Reconstruct 3D scenes.
- Track generation progress.
- Preview generated models.
- Download generation results.
- Delete personal projects.

Users must only have access to their own projects and associated files.

### 3.2. Guest User

An unauthenticated visitor.

A guest can:

- Open the application's public landing page.
- View information about the application.
- Navigate to registration or login.

A guest cannot create projects or access generated content.

### 3.3. Administrator

Administrative functionality is outside the scope of the MVP.

The system should nevertheless be designed so that administrative capabilities can be introduced in future versions.

---

## 4. Core User Scenarios

### 4.1. User Registration and Authentication

1. A visitor opens the application.
2. The visitor navigates to the registration page.
3. The visitor provides the required credentials.
4. The application validates the submitted information.
5. The account is created.
6. The user is authenticated and redirected to the project dashboard.

An existing user can authenticate using the login page.

### 4.2. Creating an Object Generation Project

1. The user opens the project creation page.
2. The user selects Object Generation.
3. The user enters a project name.
4. The user uploads one photograph in JPEG or PNG format.
5. The application validates the uploaded file.
6. The application displays an image preview.
7. The user confirms the project creation.
8. The project becomes available in the project dashboard.

### 4.3. Generating an Individual 3D Object

1. The user opens an existing object generation project.
2. The user reviews the uploaded photograph.
3. The user starts the generation process.
4. The application creates a generation task.
5. The task is added to the processing queue.
6. The user sees the current processing status.
7. Once processing is completed, the result becomes available.
8. The user opens the result page.
9. The generated object is displayed in the 3D viewer.
10. The user downloads the resulting model.

Object generation uses TripoSR.

### 4.4. Creating a Scene Reconstruction Project

1. The user opens the project creation page.
2. The user selects Scene Reconstruction.
3. The user enters a project name.
4. The user uploads multiple photographs of the same physical location.
5. The application validates uploaded files.
6. The application displays previews of all photographs.
7. The user can remove individual photographs before starting processing.
8. The user confirms project creation.
9. The project becomes available in the project dashboard.

### 4.5. Reconstructing a 3D Scene

1. The user opens an existing scene reconstruction project.
2. The user reviews the uploaded photographs.
3. The user starts the reconstruction process.
4. The application creates a background processing task.
5. COLMAP performs camera estimation and initial reconstruction.
6. OpenMVS performs dense reconstruction and mesh processing.
7. The application tracks the task status.
8. When reconstruction is completed, the generated scene becomes available.
9. The user opens the scene in the 3D viewer.
10. The user downloads the resulting 3D asset.

### 4.6. Managing Projects

A project may retain multiple generation attempts and historical
results.

Starting a new generation must not overwrite the previous
successful result.

If the latest generation attempt fails, the previous successful
result must remain available.

The user can:

- Open a list of personal projects.
- View project details.
- View the generation status.
- Open completed results.
- Retry failed generation tasks.
- Delete projects.

Deleting a project must also trigger cleanup of its associated files and generated assets.

---

## 5. Functional Requirements

Functional requirements use the following identifiers:

- FR-AUTH — Authentication.
- FR-PROJ — Project Management.
- FR-IMG — Image Management.
- FR-OBJ — Object Generation.
- FR-SCENE — Scene Reconstruction.
- FR-TASK — Task Processing.
- FR-VIEW — 3D Visualization.
- FR-EXPORT — Export and Download.

### 5.1. Authentication

**FR-AUTH-01. Registration**

The system must allow new users to create an account.

**FR-AUTH-02. Login**

The system must allow registered users to authenticate.

**FR-AUTH-03. Logout**

The system must allow authenticated users to terminate their sessions.

**FR-AUTH-04. Access Control**

The application must restrict access to personal projects and associated assets.

**FR-AUTH-05. Session Management**

The application must maintain authenticated user sessions between page navigation and browser refreshes.

Detailed authentication mechanisms are defined in the Backend Specification.

### 5.2. Project Management

**FR-PROJ-01. Project Creation**

The system must allow authenticated users to create new projects.

**FR-PROJ-02. Project Types**

Each project must have one of two generation types:

- OBJECT
- SCENE

**FR-PROJ-03. Project Name**

Every project must have a user-defined name.

**FR-PROJ-04. Project Dashboard**

The application must display a list of projects belonging to the authenticated user.

**FR-PROJ-05. Project Information**

Each project entry must display:

- Project name.
- Generation type.
- Creation date.
- Current status.
- Availability of a generated result.

**FR-PROJ-06. Project Details**

The user must be able to open a project and view its information.

**FR-PROJ-07. Project Deletion**

The user must be able to delete personal projects.

Deletion must include associated images, generated files and project metadata.

**FR-PROJ-08. Project Ownership**

The system must prevent users from accessing, modifying or deleting projects belonging to other users.

**FR-PROJ-09. Asynchronous Project Deletion**

The system must immediately make a deleted project inaccessible
through ordinary application operations.

Physical deletion of associated files and database metadata
may be performed asynchronously.

**FR-PROJ-10. Previous Result Availability**

The availability of the latest successfully generated result
must be independent of the status of the latest generation attempt.

A project with FAILED status may still contain an accessible
previously generated result.

### 5.3. Image Management

**FR-IMG-01. Supported Formats**

The application must support photographs in:

- JPEG / JPG
- PNG

**FR-IMG-02. Object Image Upload**

Object generation projects must accept exactly one source photograph.

**FR-IMG-03. Scene Image Upload**

Scene reconstruction projects must accept multiple source photographs.

**FR-IMG-04. Image Preview**

The application must display image previews before processing starts.

**FR-IMG-05. Image Removal**

The user must be able to remove uploaded photographs before generation starts.

**FR-IMG-06. File Validation**

The system must validate:

- File extension.
- Actual file format and decodability.
- MIME type.
- File size.
- Number of uploaded images.

**FR-IMG-07. Upload Feedback**

The application must inform the user about the success or failure of each upload.

**FR-IMG-08. Image Storage**

Uploaded images must be associated with the corresponding project.

**FR-IMG-09. Upload Restrictions**

Maximum file size, image count and other upload restrictions must be configurable.

**FR-IMG-10. Scene Image Guidance**

Before scene reconstruction, the application must display guidance explaining the requirements for source photographs.

The guidance must explain that:

- All photographs must show the same physical environment.
- Photographs should be captured from different viewpoints.
- Adjacent photographs should have sufficient visual overlap.
- Images should be sharp and adequately illuminated.
- The environment should remain as static as possible during capture.
- Reflective, transparent and textureless surfaces can reduce reconstruction quality.

The application must not guarantee successful reconstruction solely because the uploaded photographs pass basic file validation.

### 5.4. Object Generation

**FR-OBJ-01. Object Generation Mode**

The application must provide an Object Generation workflow.

**FR-OBJ-02. Source Image**

The workflow must use one uploaded photograph.

**FR-OBJ-03. Generation Algorithm**

The MVP must use TripoSR for individual object generation.

**FR-OBJ-04. Generation Initiation**

The user must explicitly initiate generation.

**FR-OBJ-05. Result Storage**

The generated model must be stored and associated with the corresponding project.

**FR-OBJ-06. Generation Failure**

If generation fails, the system must record the failure and make the error state available to the user.

**FR-OBJ-07. Generation Retry**

The user must be able to retry generation after a failed task, provided the source photograph remains available.

**FR-OBJ-08. Generation Result**

A successfully completed generation task must provide a downloadable 3D model.

**FR-OBJ-09. Generation Limitations**

The application must inform users that generation from one photograph involves estimating unseen geometry and may not reproduce the actual object accurately from all viewpoints.

### 5.5. Scene Reconstruction

**FR-SCENE-01. Scene Reconstruction Mode**

The application must provide a Scene Reconstruction workflow.

**FR-SCENE-02. Multiple Source Images**

The workflow must accept multiple photographs of the same physical location.

**FR-SCENE-03. Reconstruction Algorithm**

The MVP must use:

- COLMAP for feature extraction, matching, camera estimation and initial reconstruction.
- OpenMVS for dense reconstruction, mesh generation and texturing.

**FR-SCENE-04. Reconstruction Initiation**

The user must explicitly initiate scene reconstruction.

**FR-SCENE-05. Reconstruction Result**

A successfully completed reconstruction must produce a 3D scene asset.

**FR-SCENE-06. Scene Representation**

The MVP must support textured 3D geometry suitable for visualization in a browser.

The scene may be represented as one or multiple meshes.

Semantic separation into independent objects is not required.

**FR-SCENE-07. Insufficient Reconstruction Data**

If the reconstruction algorithm cannot produce a valid result because of insufficient image overlap, poor image quality or other technical problems, the task must terminate with an appropriate error state.

**FR-SCENE-08. Reconstruction Diagnostics**

Where available, the system should provide useful error information about failed reconstruction stages.

**FR-SCENE-09. Reconstruction Retry**

The user must be able to retry failed reconstruction using the existing source images.

**FR-SCENE-10. Reconstruction Limitations**

The application must inform users that reconstruction quality depends on photographic coverage, overlap, lighting, texture characteristics and camera movement.

### 5.6. Background Task Processing

**FR-TASK-01. Asynchronous Processing**

Long-running generation and reconstruction operations must execute outside HTTP request handlers.

**FR-TASK-02. Task Creation**

Starting generation must create a processing task associated with a project.

**FR-TASK-03. Task Queue**

Pending operations must be scheduled for background processing.

**FR-TASK-04. Task Status**

The application must provide the current processing status.

Project statuses:

- CREATED
- UPLOADING
- PENDING
- PROCESSING
- COMPLETED
- FAILED

Generation task statuses:

- PENDING
- PROCESSING
- COMPLETED
- FAILED
- CANCELLED

**FR-TASK-05. Status Updates**

The frontend must be able to retrieve status updates without restarting the generation task.

**FR-TASK-06. Processing Errors**

The system must record task errors and expose a user-friendly error message.

**FR-TASK-07. Task Isolation**

Failure of one generation task must not cause unrelated projects or processing tasks to fail.

**FR-TASK-08. Duplicate Execution Protection**

Repeated requests to start the same project generation must not unintentionally create multiple simultaneous executions.

**FR-TASK-09. Task Recovery**

The system should handle interrupted processing and unexpected worker termination without leaving projects permanently marked as processing.

**FR-TASK-10. Processing Progress**

The application should display meaningful processing stages when they are available.

It must not display fabricated progress percentages.

**FR-TASK-11. Task Recovery**

The system must detect generation tasks that remain in PROCESSING
after unexpected worker termination.

The system must support safe recovery or retry of interrupted tasks.

**FR-TASK-12. Internal Cancellation**

The system must support cancellation of pending or processing tasks
when their parent project is being deleted.

Cancellation is an internal lifecycle operation and does not require
a user-facing cancellation feature in the MVP.

**FR-TASK-13. Duplicate Delivery Protection**

Repeated delivery of the same background task message must not
produce duplicate conflicting generation results.

### 5.7. 3D Visualization

**FR-VIEW-01. Browser-Based Viewer**

The application must provide an interactive 3D viewer.

**FR-VIEW-02. Supported Input**

The viewer must support GLB/GLTF assets.

**FR-VIEW-03. Object Display**

The viewer must display generated individual objects.

**FR-VIEW-04. Scene Display**

The viewer must display reconstructed scenes.

**FR-VIEW-05. Camera Controls**

The user must be able to:

- Rotate the camera around the model.
- Zoom in and out.
- Pan the camera.
- Reset the camera position.

**FR-VIEW-06. Initial Camera Position**

The viewer must automatically position the camera to make the loaded model visible.

**FR-VIEW-07. Loading Feedback**

The viewer must indicate when a 3D asset is loading.

**FR-VIEW-08. Loading Errors**

The application must display an appropriate error message if the model cannot be loaded.

**FR-VIEW-09. Material and Texture Support**

The viewer must render supported geometry, materials and textures.

### 5.8. Export and Download

**FR-EXPORT-01. Model Download**

Users must be able to download completed generation results.

**FR-EXPORT-02. Primary Export Format**

GLB must be supported as the primary export format for the MVP.

**FR-EXPORT-03. Result Availability**

Download functionality must only be available when a valid generation result exists.

**FR-EXPORT-04. File Integrity**

The downloaded file must correspond to the generated asset stored by the application.

Support for OBJ and STL can be considered for subsequent versions.

---

## 6. Application Pages

The MVP must include the following pages.

### 6.1. Landing Page

Purpose: introduce the application and direct visitors to its main functionality.

Required elements:

- Application name and branding.
- Short product description.
- Description of Object Generation.
- Description of Scene Reconstruction.
- Examples or illustrations of generated 3D content.
- Registration and login entry points.

### 6.2. Registration Page

Purpose: create a user account.

Required elements:

- Email input.
- Password input.
- Password confirmation.
- Registration button.
- Link to the login page.
- Validation and error messages.

### 6.3. Login Page

Purpose: authenticate an existing user.

Required elements:

- Email input.
- Password input.
- Login button.
- Link to registration.
- Authentication error messages.

### 6.4. Project Dashboard

Purpose: manage user projects.

Required elements:

- Project list.
- Project creation button.
- Project name.
- Generation type.
- Creation date.
- Processing status.
- Navigation to project details.
- Project deletion action.

Provide an informative empty state when the user has no projects.

### 6.5. Project Creation Page

Purpose: create a new generation project.

Required elements:

- Project name.
- Generation mode selection.
- Image upload area.
- Uploaded image previews.
- Image removal controls.
- Upload validation messages.
- Generation-specific instructions.
- Project creation action.

The available upload interface must depend on the selected generation mode.

### 6.6. Project Details Page

Purpose: review project information and manage generation.

Required elements:

- Project name.
- Generation mode.
- Creation date.
- Uploaded photographs.
- Current status.
- Generation action when processing has not started.
- Processing status and error information.
- Link to the result when generation is completed.
- Retry action after failure.
- Project deletion action.

### 6.7. 3D Result Page

Purpose: visualize and download the generated asset.

Required elements:

- Interactive 3D viewer.
- Project name.
- Generation mode.
- Generation status.
- Model loading indicator.
- Camera controls.
- Download button.
- Navigation back to the project.

---

## 7. Non-Functional Requirements

### 7.1. Performance

**NFR-PERF-01. API Responsiveness**

Ordinary API operations must return promptly and must not wait for ML processing to finish.

As a preliminary MVP target, metadata operations should normally complete within 2 seconds under development test conditions, excluding file transfer and background generation.

**NFR-PERF-02. Asynchronous Operations**

Object generation and scene reconstruction must not block the application's request-handling process.

**NFR-PERF-03. Viewer Performance**

The 3D viewer should load models efficiently and provide usable camera interaction.

Large scene performance must be evaluated separately from individual object performance.

**NFR-PERF-04. Configurable Limits**

Resource-intensive operations must have configurable upload limits and worker concurrency.

No fixed generation completion time is guaranteed because it depends on hardware and input complexity.

### 7.2. Security

**NFR-SEC-01. Authentication**

Protected application functionality must require authentication.

**NFR-SEC-02. Authorization**

The backend must verify project ownership for all project-related operations.

**NFR-SEC-03. File Validation**

Uploaded files must be validated before being processed.

**NFR-SEC-04. File Access**

Stored assets must not be publicly accessible by predictable or directly guessable file paths.

**NFR-SEC-05. Input Validation**

All API input must be validated.

**NFR-SEC-06. Error Handling**

Internal stack traces, server paths and sensitive implementation details must not be exposed to users.

### 7.3. Reliability

**NFR-REL-01. Task Isolation**

A failure in one ML task must not affect the availability of the main application.

**NFR-REL-02. Failure Reporting**

Failed operations must be recorded with sufficient diagnostic information.

**NFR-REL-03. File Consistency**

The application must prevent the creation of invalid project references to missing result files.

**NFR-REL-04. Cleanup**

Deletion of projects must trigger cleanup of associated files and assets.

### 7.4. Usability

**NFR-UX-01. Interface Simplicity**

The interface must be understandable to users without professional 3D modeling experience.

**NFR-UX-02. Consistency**

All application pages must use consistent navigation, components and visual styling.

**NFR-UX-03. Feedback**

The application must clearly communicate upload, processing, success and failure states.

**NFR-UX-04. Instructions**

The application must provide instructions for preparing source photographs.

### 7.5. Compatibility

**NFR-COMPAT-01. Browsers**

The application must support recent desktop versions of Chrome, Firefox, Edge and Safari.

**NFR-COMPAT-02. Responsive Layout**

The interface must adapt to desktop and tablet screen sizes.

Mobile support is desirable but not a primary MVP requirement.

### 7.6. Maintainability

**NFR-MAINT-01. Modularity**

The application must separate frontend, backend, persistence, file management and ML processing responsibilities.

**NFR-MAINT-02. Extensibility**

New generation algorithms should be integrable without rewriting the project's core business logic.

**NFR-MAINT-03. Documentation**

Important interfaces, configuration parameters and application startup procedures must be documented.

**NFR-MAINT-04. Configuration**

Environment-specific parameters must be configurable rather than hardcoded.

---

## 8. MVP Scope and Prioritization

### 8.1. Must Have

The following functionality is mandatory for the MVP:

- User registration and login.
- Project creation and deletion.
- Project dashboard.
- JPEG and PNG upload.
- Single-image object generation using TripoSR.
- Multi-image scene reconstruction using COLMAP and OpenMVS.
- Asynchronous processing.
- Processing status tracking.
- Error handling.
- Browser-based 3D viewer.
- GLB download.
- Docker Compose deployment.

### 8.2. Should Have

The following functionality is desirable if it does not significantly delay the MVP:

- Informative processing stages.
- Detailed reconstruction error diagnostics.
- Retry of failed tasks.
- Project descriptions.
- Better handling of large 3D scenes.
- OBJ export.
- Mobile-friendly layout.

### 8.3. Out of Scope

The following features are explicitly excluded from the MVP:

- Manual editing of 3D geometry.
- Semantic separation of a scene into independently editable objects.
- AI-based generation of new environments.
- Text-to-3D generation.
- Video-based reconstruction.
- Animation and rigging.
- Collaborative editing.
- Sharing projects with other users.
- Public model galleries.
- Integrated marketplace.
- Advanced material editing.
- Advanced 3D scene composition tools.
- Billing and subscription management.

---

## 9. Acceptance Criteria

The MVP is considered functionally complete when the following scenarios can be successfully demonstrated.

### AC-01. User Registration

Given an unauthenticated visitor,

When the visitor submits valid registration information,

Then the system creates an account and allows the user to access the application.

### AC-02. Authentication

Given an existing registered user,

When the user submits valid credentials,

Then the system authenticates the user and opens the project dashboard.

### AC-03. Object Project Creation

Given an authenticated user,

When the user creates an Object Generation project and uploads a valid JPEG or PNG photograph,

Then the application creates a project and displays it in the dashboard.

### AC-04. Object Image Validation

Given an Object Generation project,

When the user attempts to upload an unsupported or invalid file,

Then the application rejects the file and displays a validation message.

### AC-05. Object Generation

Given a valid Object Generation project,

When the user starts generation,

Then the system schedules a background task, processes the photograph using TripoSR and stores the generated result.

### AC-06. Scene Project Creation

Given an authenticated user,

When the user creates a Scene Reconstruction project and uploads multiple valid photographs,

Then the application creates the project and displays the uploaded images.

### AC-07. Scene Reconstruction

Given a Scene Reconstruction project with suitable photographs,

When the user starts reconstruction,

Then the system executes the COLMAP and OpenMVS processing pipeline and stores the resulting scene when processing succeeds.

### AC-08. Task Status

Given an active generation task,

When the user opens the project details page,

Then the application displays the current task status.

### AC-09. Task Failure

Given a generation task that encounters an error,

When processing terminates,

Then the application marks the task as FAILED and provides an appropriate error message.

### AC-10. 3D Visualization

Given a successfully generated GLB asset,

When the user opens the result page,

Then the application loads the asset into the 3D viewer and allows camera interaction.

### AC-11. Model Download

Given a completed generation project,

When the user selects Download,

Then the application provides the corresponding generated GLB file.

### AC-12. Project Isolation

Given two different authenticated users,

When one user attempts to access another user's project,

Then the backend denies the operation.

### AC-13. Project Deletion

Given an existing user project,

When its owner deletes it,

Then the project is removed and its associated files are scheduled for cleanup.

### AC-14. Docker Deployment

Given a correctly configured development environment,

When the user starts the application using Docker Compose,

Then the required application services become available and frontend/backend communication works.

---

## 10. Product Constraints and Assumptions

### 10.1. Object Generation Constraints

- TripoSR is used for single-image reconstruction.
- Unseen geometry is estimated rather than recovered from actual observations.
- Generated results may contain geometric inaccuracies.
- Output quality depends on the input photograph.

### 10.2. Scene Reconstruction Constraints

- All input photographs must represent the same physical environment.
- Sufficient overlap between photographs is required.
- Camera movement and image quality affect reconstruction quality.
- Dynamic objects, reflective surfaces and transparent materials can negatively affect reconstruction.
- Some photographs may not be successfully registered by COLMAP.
- Reconstruction may fail even when all photographs pass file validation.

### 10.3. Infrastructure Constraints

- GPU availability may be required for efficient TripoSR processing.
- COLMAP and OpenMVS processing can be computationally intensive.
- Generation time depends on hardware and input complexity.
- Local storage is sufficient for the MVP.
- Future deployment may separate application services and ML workers across different machines.

### 10.4. Product Assumptions

- The initial application is intended for individual users.
- Each project uses one generation mode.
- A project contains one set of source photographs.
- A generation task belongs to exactly one project.
- The primary result format is GLB.
- The system does not guarantee professional-grade reconstruction quality.

---

## 11. Related Specifications

This document defines the product-level requirements.

Detailed technical requirements are covered by:

- `00_project_overview.md` — project context and development principles.
- `02_ui_ux_specification.md` — visual design and user interface.
- `03_frontend_specification.md` — frontend implementation.
- `04_backend_specification.md` — REST API and backend logic.
- `05_database_specification.md` — data model and persistence.
- `06_object_generation.md` — TripoSR integration.
- `07_scene_reconstruction.md` — COLMAP and OpenMVS integration.
- `08_infrastructure.md` — Docker and background processing.
- `09_testing.md` — test strategy and quality requirements.
- `10_development_roadmap.md` — implementation sequence.
- `AI_DEVELOPMENT_GUIDE.md` — development workflow, quality gates and rules for AI coding agents.

All subsystem implementations must satisfy the relevant product requirements defined in this document.