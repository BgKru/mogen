# 03 — Frontend Specification

## 1. Document Purpose

This document defines the technical architecture and implementation requirements for the frontend application.

It describes:
- Frontend architecture.
- Project directory structure.
- Technologies and dependencies.
- Routing and navigation.
- State management.
- API integration.
- Authentication and authorization.
- Image uploading and validation.
- Project management interfaces.
- Background task tracking.
- Three.js integration.
- Error handling.
- Testing requirements.

The frontend must implement the UI/UX requirements defined in `02_ui_ux_specification.md` and satisfy the functional requirements defined in `01_product_requirements.md`.

This document describes HOW the frontend should be implemented.

---

## 2. Technology Stack

### 2.1. Core Technologies

| Area | Technology |
|---|---|
| Framework | React |
| Programming Language | TypeScript |
| Build Tool | Vite |
| Styling | Tailwind CSS |
| Routing | React Router |
| 3D Rendering | Three.js |
| React 3D Integration | React Three Fiber |
| 3D Utilities | @react-three/drei |
| Server State | TanStack Query |
| HTTP Client | Axios |
| Forms | React Hook Form |
| Form Validation | Zod |

### 2.2. Development Dependencies

Recommended development tools:

- ESLint — code quality and linting.
- Prettier — formatting.
- Vitest — unit and integration testing.
- React Testing Library — component testing.
- Playwright — end-to-end testing.
- TypeScript Compiler — static type checking.

### 2.3. Dependency Guidelines

Use dependencies only when they provide clear functionality.

Avoid introducing large UI frameworks or unnecessary libraries.

Prefer reusable components implemented with React and Tailwind CSS.

Use React Three Fiber and Drei to simplify integration with Three.js without hiding the underlying 3D rendering functionality.

Do not introduce a separate global state management library unless the application complexity demonstrates a need for one.

---

## 3. Frontend Architecture

### 3.1. Architectural Approach

Use a modular, feature-oriented React architecture.

Separate application-level configuration, pages, features, shared components and domain entities.

The frontend must not contain backend business logic or machine learning implementation details.

Main architectural layers:

1. App — application initialization, routing and providers.
2. Pages — application routes and page composition.
3. Features — user-facing functionality.
4. Entities — domain models and shared domain components.
5. Shared — reusable infrastructure, API clients and UI components.

### 3.2. Proposed Directory Structure

Use the following project structure:

```text
frontend/
│
├── public/
│   ├── images/
│   └── icons/
│
├── src/
│   │
│   ├── app/
│   │   ├── providers/
│   │   │   ├── AppProviders.tsx
│   │   │   ├── QueryProvider.tsx
│   │   │   └── AuthProvider.tsx
│   │   │
│   │   ├── router/
│   │   │   ├── AppRouter.tsx
│   │   │   ├── ProtectedRoute.tsx
│   │   │   └── routes.ts
│   │   │
│   │   └── styles/
│   │       ├── globals.css
│   │       └── theme.css
│   │
│   ├── pages/
│   │   ├── LandingPage/
│   │   ├── LoginPage/
│   │   ├── RegisterPage/
│   │   ├── DashboardPage/
│   │   ├── CreateProjectPage/
│   │   ├── ProjectDetailsPage/
│   │   └── ModelViewerPage/
│   │
│   ├── features/
│   │   │
│   │   ├── auth/
│   │   │   ├── api/
│   │   │   ├── components/
│   │   │   ├── hooks/
│   │   │   └── schemas/
│   │   │
│   │   ├── projects/
│   │   │   ├── api/
│   │   │   ├── components/
│   │   │   ├── hooks/
│   │   │   └── schemas/
│   │   │
│   │   ├── image-upload/
│   │   │   ├── components/
│   │   │   ├── hooks/
│   │   │   ├── utils/
│   │   │   └── types/
│   │   │
│   │   ├── object-generation/
│   │   │   ├── api/
│   │   │   ├── components/
│   │   │   └── hooks/
│   │   │
│   │   ├── scene-reconstruction/
│   │   │   ├── api/
│   │   │   ├── components/
│   │   │   └── hooks/
│   │   │
│   │   └── model-viewer/
│   │       ├── components/
│   │       ├── hooks/
│   │       ├── utils/
│   │       └── types/
│   │
│   ├── entities/
│   │   ├── project/
│   │   │   ├── model/
│   │   │   ├── types/
│   │   │   └── components/
│   │   │
│   │   └── generation-task/
│   │       ├── types/
│   │       └── model/
│   │
│   ├── shared/
│   │   ├── api/
│   │   │   ├── client.ts
│   │   │   ├── endpoints.ts
│   │   │   └── errors.ts
│   │   │
│   │   ├── components/
│   │   │   ├── Button/
│   │   │   ├── Input/
│   │   │   ├── Modal/
│   │   │   ├── Tooltip/
│   │   │   ├── Toast/
│   │   │   └── LoadingSpinner/
│   │   │
│   │   ├── hooks/
│   │   ├── lib/
│   │   ├── types/
│   │   └── utils/
│   │
│   ├── main.tsx
│   └── vite-env.d.ts
│
├── tests/
│   ├── integration/
│   └── e2e/
│
├── .env.example
├── .gitignore
├── eslint.config.js
├── package.json
├── tsconfig.json
├── vite.config.ts
├── index.html
└── README.md
```

This structure is a recommended starting point.

Do not create empty modules or abstractions without an actual implementation requirement.

### 3.3. Module Responsibilities

**App**

Responsible for initializing the application, configuring providers and defining routes.

**Pages**

Responsible for composing features and shared components into complete application pages.

**Features**

Contain user-facing functionality, including authentication, project management, image uploading and generation workflows.

**Entities**

Contain domain-level data structures and reusable project-related components.

**Shared**

Contains infrastructure and reusable functionality that does not belong to a specific business domain.

### 3.4. Separation of Responsibilities

The frontend must not:

- Run TripoSR.
- Execute COLMAP or OpenMVS.
- Perform heavy image reconstruction.
- Access PostgreSQL directly.
- Access backend file system paths.
- Implement ML processing logic.
- Store generated 3D assets as permanent browser-side application data.

All generation operations must be initiated through the backend REST API.

---

## 4. Application Initialization

### 4.1. Entry Point

The application must be initialized through `main.tsx`.

Initialization must include:

- React root rendering.
- Global styles.
- Application providers.
- Router initialization.

### 4.2. Application Providers

Use a shared provider composition.

Required providers:

- QueryClientProvider — TanStack Query.
- AuthProvider — authentication state.
- RouterProvider or BrowserRouter — routing.

The provider hierarchy must be centralized in `AppProviders.tsx`.

Avoid duplicating provider initialization across pages.

### 4.3. Environment Configuration

Use Vite environment variables.

Required configuration:

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

Additional configurable frontend settings may include:

```env
VITE_TASK_POLL_INTERVAL=3000
```

Environment variables exposed through Vite must not contain passwords, private keys or other secrets.

Backend credentials and database connection strings must never be included in the frontend bundle.

### 4.4. Development and Production Modes

The frontend must support:

- Local development using Vite.
- Production build.
- Docker-based deployment.
- Runtime configuration appropriate for the deployment environment.

Frontend configuration must not depend on hardcoded local development addresses.

---

## 5. Routing and Navigation

### 5.1. Routing Library

Use React Router.

All page navigation must be handled through client-side routing.

### 5.2. Route Structure

Implement the following routes:

| Route | Page | Access |
|---|---|---|
| `/` | LandingPage | Public |
| `/login` | LoginPage | Public |
| `/register` | RegisterPage | Public |
| `/dashboard` | DashboardPage | Authenticated |
| `/projects/new` | CreateProjectPage | Authenticated |
| `/projects/:id` | ProjectDetailsPage | Authenticated |
| `/projects/:id/result` | ModelViewerPage | Authenticated |

### 5.3. Protected Routes

Pages requiring authentication must be protected.

Unauthenticated users attempting to access protected routes must be redirected to the login page.

After successful authentication, the application should return users to their originally requested page when appropriate.

Frontend route protection is a usability mechanism only.

The backend must independently validate authentication and project ownership for every protected API operation.

### 5.4. Unknown Routes

Display a dedicated Not Found page or an appropriate fallback.

Do not render an empty application page when an unknown route is requested.

### 5.5. Route Parameters

Project pages must obtain the project identifier from the route.

Validate the identifier before initiating project-related API requests.

Handle invalid identifiers and missing projects gracefully.

Project deletion returns HTTP 202 Accepted.

After successful acceptance:
- Immediately remove the project from the visible dashboard.
- Do not wait for physical file deletion.
- Treat backend cleanup as an asynchronous operation.

---

## 6. State Management

### 6.1. General Approach

Use different mechanisms for different types of application state.

The primary approach:

| State Type | Recommended Solution |
|---|---|
| Server data | TanStack Query |
| Form state | React Hook Form |
| Form validation | Zod |
| Authentication context | React Context |
| Local UI state | React useState / useReducer |
| Viewer controls | Local component state |

Avoid duplicating server data in global React state.

### 6.2. Server State

TanStack Query must manage data retrieved from the backend.

Examples:

- Current user.
- Project list.
- Project details.
- Uploaded image metadata.
- Generation status.
- Generation result metadata.

Use query hooks for data retrieval and mutation hooks for operations that change server-side data.

Examples:

```text
useProjects()
useProject(projectId)
useCurrentUser()

useCreateProject()
useDeleteProject()
useUploadImages()
useStartGeneration()
useRetryGeneration()
```

Query keys must be centralized and consistently structured.

Example:

```typescript
[
  "projects"
]

[
  "projects",
  projectId
]

[
  "projects",
  projectId,
  "status"
]
```

Invalidate affected queries after successful mutations.

### 6.3. Local State

Use local React state for temporary interface information.

Examples:

- Selected generation mode.
- Selected local image files.
- Expanded information panels.
- Modal visibility.
- Viewer background settings.
- Camera control state.

Temporary form state must not be treated as persisted project data until successfully saved through the API.

### 6.4. Authentication State

Authentication state must be available throughout the application.

After successful registration or login:

1. Initialize the authenticated user state.
2. Retrieve the CSRF token.
3. Keep the CSRF token in application memory.
4. Attach X-CSRF-Token to authenticated state-changing requests.

After application initialization, retrieve the CSRF token
for an already authenticated session.

The CSRF token must not be stored in localStorage or sessionStorage.

The application must support:

- Checking the current authentication state.
- Loading the authenticated user.
- Login.
- Registration.
- Logout.
- Handling expired sessions.
- Redirecting unauthenticated users.

Do not store authentication tokens in localStorage or sessionStorage.

Prefer secure, HttpOnly cookies managed by the backend.

When cookie-based authentication is used, configure Axios to send credentials and implement CSRF protection according to the backend authentication contract.

The exact authentication mechanism must be defined in the Backend Specification.

---

## 7. API Integration

### 7.1. General Requirements

The frontend communicates with the backend exclusively through REST API endpoints.

Use Axios with a centralized API client.

The API client must provide:

- Base URL configuration.
- Authentication credentials handling.
- Request and response interceptors where necessary.
- Common error processing.
- Consistent timeout configuration.
- Type-safe request and response definitions.

### 7.2. API Client

Create a centralized API client in:

`shared/api/client.ts`

Example:

```typescript
import axios from "axios";

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  withCredentials: true,
  timeout: 30000,
  headers: {
    Accept: "application/json",
  },
});
```

The actual credential configuration must follow the backend authentication contract.

Do not configure automatic retry for non-idempotent operations without explicit retry and idempotency rules.

### 7.3. API Modules

Separate API operations by domain.

Suggested modules:

```text
features/
├── auth/api/authApi.ts
├── projects/api/projectsApi.ts
├── object-generation/api/objectGenerationApi.ts
└── scene-reconstruction/api/sceneReconstructionApi.ts
```

Shared API functionality must remain in `shared/api`.

### 7.4. API Operations

The frontend must support the following operations:

**Authentication**

```text
GET  /api/v1/auth/csrf
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me
```

**Projects**

```text
POST   /api/v1/projects
GET    /api/v1/projects
GET    /api/v1/projects/{id}
DELETE /api/v1/projects/{id}
```

**Images**

```text
GET    /api/v1/projects/{id}/images/{image_id}/content
POST   /api/v1/projects/{id}/images
GET    /api/v1/projects/{id}/images
DELETE /api/v1/projects/{id}/images/{image_id}
```

**Generation**

```text
POST /api/v1/projects/{id}/generate
GET  /api/v1/projects/{id}/status
```

**Results**

```text
GET /api/v1/projects/{id}/result
GET /api/v1/projects/{id}/download
```

These endpoints describe the initial frontend integration requirements.

Exact request payloads, response schemas, HTTP status codes and error formats must be defined centrally in `architecture/api_contracts.md` and implemented consistently by the backend.

Do not independently invent or duplicate API response structures.

### 7.5. Type Definitions

Use TypeScript interfaces or types for all API requests and responses.

Suggested domain types:

```typescript
export type ProjectType = "OBJECT" | "SCENE";

export type ProjectStatus =
  | "CREATED"
  | "UPLOADING"
  | "PENDING"
  | "PROCESSING"
  | "COMPLETED"
  | "FAILED";

export type TaskStatus =
  | "PENDING"
  | "PROCESSING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export interface Project {
  id: string;
  name: string;
  type: ProjectType;
  status: ProjectStatus;
  createdAt: string;
  updatedAt: string;
  resultAvailable: boolean;
}

export interface UploadedImage {
  id: string;
  projectId: string;
  filename: string;
  contentType: string;
  size: number;
  createdAt: string;
}

export interface GenerationTask {
  id: string;
  projectId: string;
  status: TaskStatus;
  stage?: string | null;
  message?: string | null;
  errorCode?: string | null;
  errorMessage?: string | null;
}

export interface GenerationResult {
  projectId: string;
  format: "GLB";
  fileSize: number;
  createdAt: string;
}
```
The backend API uses snake_case field names.

Frontend API DTOs must preserve the exact backend response structure.

Conversion to camelCase must be performed through an explicit
mapping layer before exposing API data to frontend domain components.

Do not mix snake_case and camelCase in the same API DTO.

The definitions above represent the frontend domain model.

Adapt property names and response mapping to the canonical backend API contracts. Do not assume the backend uses camelCase when Python APIs may expose snake_case.

Prefer a consistent transformation layer when mapping backend responses to frontend models.

### 7.6. Error Handling

Implement centralized API error handling.

The frontend must correctly handle:

- 400 — invalid request.
- 401 — unauthenticated.
- 403 — forbidden.
- 404 — resource not found.
- 409 — conflicting operation.
- 413 — file too large.
- 415 — unsupported media type.
- 422 — validation error.
- 429 — request rate limit.
- 500 — internal server error.
- 502 / 503 / 504 — unavailable or timed-out upstream service.

Display user-friendly messages.

Do not expose server stack traces, internal file paths or sensitive backend details.

Preserve field-level validation information where available.

### 7.7. API Request Lifecycle

All API-dependent interfaces must handle:

- Initial loading.
- Successful response.
- Empty response.
- Validation error.
- Authorization error.
- Server error.
- Network error.

Avoid rendering undefined data as if it were an empty successful result.

---

## 8. Authentication Implementation

### 8.1. Registration

Implement a registration form using React Hook Form and Zod.

Fields:

- Email.
- Password.
- Password confirmation.

Requirements:

- Required field validation.
- Email format validation.
- Password confirmation validation.
- Server-side validation error display.
- Loading state during submission.
- Successful registration handling.

### 8.2. Login

Implement a login form with email and password.

After successful authentication:

- Update authentication state.
- Invalidate or refresh the current user query.
- Redirect the user to the dashboard or requested protected route.

### 8.3. Logout

Logout must:

1. Send the logout request to the backend.
2. Clear client-side authentication state.
3. Clear or invalidate user-specific server queries.
4. Redirect the user to the landing page.

If the logout request fails because the session is already invalid, the frontend must still safely return to an unauthenticated state.

### 8.4. Authentication Initialization

When the application starts:

1. Check whether an authenticated session exists.
2. Request the current user.
3. Update authentication state.
4. Render the appropriate routes.

Avoid redirecting users while the initial authentication check is still running.

---

## 9. Project Management Implementation

### 9.1. Project Dashboard

Implement the project dashboard using reusable project cards.

The dashboard must:

- Retrieve projects from the backend.
- Display the project list.
- Display project type.
- Display creation date.
- Display current status.
- Display result availability.
- Allow navigation to project details.
- Support project deletion.

Implement the appropriate loading, empty and error states.

### 9.2. Project Creation

The project creation workflow must collect:

- Project name.
- Project type.
- Source photographs.

The upload interface must depend on the selected project type.

Object projects accept one photograph.

Scene projects accept multiple photographs.

The frontend must not automatically start generation after project creation.

### 9.3. Project Details

The project details page must retrieve information from the backend using the project identifier.

Display:

- Project metadata.
- Source image information.
- Generation type.
- Current status.
- Available actions.

Refresh information after relevant mutations.

### 9.4. Project Deletion

Before deletion, display a confirmation dialog.

After successful deletion:

- Invalidate the project list.
- Remove the project from the dashboard.
- Redirect to the dashboard when deletion was initiated from the project details page.

The backend remains responsible for deleting associated files.

---

## 10. Image Upload Implementation

### 10.1. Upload Component

Image uploads for the same project must be coordinated to prevent
conflicting project state transitions and duplicate image positions.

For the MVP, the frontend should upload selected images sequentially.

Each uploaded image must be considered successful only after
the backend returns HTTP 201.

Failed uploads must remain available for individual retry.

The backend must assign image positions consistently.

Create a reusable image upload component.

Recommended component:

`ImageDropzone`

It must support:

- Drag and drop.
- File selection dialog.
- File format validation.
- File size validation.
- Image preview.
- File removal.
- Upload progress.
- Upload error display.

The component must support both single-image and multiple-image modes.

### 10.2. File Restrictions

Supported formats:

- JPEG / JPG.
- PNG.

The file input should use appropriate accepted MIME types:

```html
accept="image/jpeg,image/png"
```

Client-side validation must check:

- File extension.
- MIME type.
- Actual image decoding.
- File size.
- Maximum number of images.

Browser validation is intended to improve user experience.

The backend remains authoritative and must independently validate every uploaded file.

Maximum file size and image count must come from configuration consistent with backend limits.

Do not rely on frontend validation as a security mechanism.

### 10.3. Object Generation Upload

For Object Generation:

- Accept exactly one photograph.
- Display one preview.
- Prevent adding additional images.
- Allow replacement or removal before upload.
- Do not allow generation without a valid uploaded image.

### 10.4. Scene Reconstruction Upload

For Scene Reconstruction:

- Accept multiple photographs.
- Display uploaded image thumbnails in a responsive grid.
- Show the number of selected images.
- Allow individual image removal.
- Preserve the order of selected images where practical.
- Display relevant guidance for photogrammetry input.

Do not guarantee reconstruction success based exclusively on the number of selected images.

### 10.5. Image Previews

Use temporary browser object URLs for image previews.

Create previews using `URL.createObjectURL()`.

Revoke object URLs when:

- An image is removed.
- The upload form is cleared.
- The component is unmounted.

Do not permanently store local preview URLs in the database or project metadata.

### 10.6. Upload Progress

Display upload progress for large files.

The upload implementation may use Axios upload progress events.

When uploading several images:

- Display individual file states.
- Display aggregate progress when available.
- Handle partial upload failures.
- Allow failed uploads to be retried.
- Prevent generation from starting until all required uploads have succeeded.

Do not report an upload as completed until the backend confirms successful storage.

### 10.7. Project Creation and Upload Sequence

The frontend must coordinate project creation and image uploading.

Recommended sequence:

1. Validate project name and generation type.
2. Validate selected images.
3. Create the project through the API.
4. Upload the source images to the created project.
5. Retrieve the project and its uploaded image metadata.
6. Navigate to the project details page.

If uploading fails after project creation:

- Preserve the project.
- Preserve successfully uploaded images.
- Display failed upload information.
- Allow the user to retry failed uploads.
- Do not start generation automatically.

The frontend must not create duplicate projects because of repeated button clicks.

---

## 11. Generation Task Tracking

### 11.1. General Requirements

Generate a new Idempotency-Key for each distinct generation action.

Reuse the same key only when retrying the same HTTP request
because its previous outcome is uncertain.

A manual generation retry after a failed task must use a new key.

If a task fails but a previous result exists, keep the result viewer
and download functionality available.

Object generation and scene reconstruction are long-running operations.

The frontend must not hold an HTTP request open while processing is running.

All generation operations must be initiated through the backend API and tracked separately.

### 11.2. Generation Initiation

When the user starts generation:

1. Validate the current project state.
2. Disable the generation action while the request is pending.
3. Submit the generation request.
4. Receive task information from the backend.
5. Invalidate the project and status queries.
6. Display the current processing state.

The backend must prevent duplicate concurrent executions.

Frontend button disabling is not a replacement for backend duplicate-execution protection.

### 11.3. Task Status Polling

Use TanStack Query to periodically retrieve task status.

The polling strategy must:

- Poll while the task is PENDING or PROCESSING.
- Stop polling when the task reaches COMPLETED or FAILED.
- Reduce unnecessary requests when the browser tab is inactive.
- Invalidate project and result queries after task completion.
- Handle temporary network failures without creating another generation task.

Use a configurable polling interval.

The default development interval may be approximately 3 seconds.

Do not implement WebSockets for the MVP unless polling proves insufficient.

### 11.4. Processing Stages

The interface may display processing stages supplied by the backend.

Object Generation may display:

- Image preparation.
- Model generation.
- Model export.

Scene Reconstruction may display:

- Image preparation.
- Feature extraction and matching.
- Camera estimation.
- Dense reconstruction.
- Mesh processing.
- Texture generation.
- Model export.

Not every stage must be available from every algorithm.

The frontend must display only actual processing information returned by the backend.

### 11.5. Progress Representation

If the backend provides a reliable progress percentage, the frontend may display a progress bar.

If only a processing status or stage is available, display an indeterminate progress indicator and the current stage.

Never invent percentage values or simulate successful progress updates.

### 11.6. Task Failure

If processing fails:

- Stop polling after the terminal FAILED status is received.
- Display the available user-friendly error message.
- Preserve the uploaded photographs.
- Display the retry action when the backend permits it.
- Allow the user to return to the project dashboard.

### 11.7. Task Completion

After successful processing:

- Stop status polling.
- Refresh project information.
- Retrieve result metadata.
- Enable the result viewer.
- Enable model download.

The result viewer must not be opened before a valid result is available.

---

## 12. Three.js and React Three Fiber Integration

### 12.1. General Requirements

Use Three.js through React Three Fiber.

The 3D viewer must be implemented as an independent feature module.

Recommended structure:

```text
features/model-viewer/
│
├── components/
│   ├── ModelViewer.tsx
│   ├── ModelCanvas.tsx
│   ├── ModelScene.tsx
│   ├── ViewerToolbar.tsx
│   ├── ViewerControls.tsx
│   ├── ViewerLoading.tsx
│   └── ViewerError.tsx
│
├── hooks/
│   ├── useModelLoader.ts
│   └── useViewerControls.ts
│
├── utils/
│   ├── modelBounds.ts
│   └── modelCleanup.ts
│
└── types/
    └── viewer.types.ts
```

### 12.2. Supported Model Format

The primary viewer format is GLB.

GLB is preferred because it can contain geometry, materials and textures in one file.

The viewer must support:

- GLB loading.
- Mesh geometry.
- Materials.
- Embedded textures.
- Model transformations.
- Camera controls.
- Lighting.

Support for external texture references is not required for the initial MVP if results are exported as self-contained GLB files.

### 12.3. Model Loading

Use `GLTFLoader` through React Three Fiber or a compatible Drei abstraction.

The application must:

1. Retrieve authorized model data from the backend.
2. Load the model.
3. Display a loading state.
4. Handle loading failures.
5. Add the loaded model to the Three.js scene.
6. Correctly release temporary resources when the viewer is closed.

When assets require authentication, retrieve them through the authorized API.

For the MVP, a suitable approach is to fetch the GLB as a Blob using the authenticated API client, create a temporary object URL and load it using GLTFLoader.

Revoke the object URL and dispose of temporary resources when they are no longer needed.

Avoid exposing private file storage paths.

### 12.4. Viewer Canvas

Use the React Three Fiber Canvas component.

Configure:

- Renderer.
- Camera.
- Scene.
- Lighting.
- Background.
- Camera controls.

The canvas must resize correctly with its parent container.

Use suitable rendering settings without introducing unnecessarily expensive effects.

### 12.5. Lighting

Provide neutral lighting that makes object geometry and material characteristics visible.

The viewer may use:

- Ambient or hemisphere lighting.
- Directional lighting.
- Additional fill lighting when required.

Avoid excessive lighting that changes the apparent appearance of reconstructed textures.

### 12.6. Camera Controls

Implement camera controls using OrbitControls or Drei.

Required operations:

- Rotate.
- Zoom.
- Pan.
- Reset camera position.

Mouse and touch interaction should be supported where practical.

### 12.7. Model Positioning

When a model is loaded:

- Calculate its bounding box.
- Determine its approximate center.
- Center the model for visualization without altering the exported asset.
- Set the initial camera position based on model dimensions.
- Choose appropriate camera near and far clipping planes.
- Ensure that the model is visible within the viewport.

Provide a Fit to View action.

### 12.8. Viewer Toolbar

Implement a compact toolbar with:

- Reset Camera.
- Fit to View.
- Grid Toggle.
- Fullscreen Toggle.
- Background Toggle, if implemented.

Each control must provide a tooltip or accessible label.

### 12.9. Grid and Ground Plane

An optional grid or ground plane may be enabled.

It should help users understand spatial orientation without interfering with texture visualization.

The grid must be toggleable.

### 12.10. Loading and Error States

The viewer must support:

**Loading**

Show a loading indicator while downloading and parsing the model.

**Loaded**

Render the model and enable camera controls.

**Error**

Display an explanatory message when model loading fails.

**Empty**

Do not render an empty viewer as a successful result when no model asset is available.

### 12.11. Scene Performance

Scene reconstruction results may be significantly larger than individual objects.

The viewer should:

- Avoid unnecessary React re-renders.
- Avoid duplicating large geometry resources.
- Clean up resources when changing projects.
- Use appropriate camera clipping planes.
- Provide a loading indicator during model parsing.
- Handle model loading failures gracefully.

Advanced level-of-detail systems and aggressive mesh optimization are outside the frontend MVP scope.

---

## 13. Frontend Styling

### 13.1. Design System

Implement the design system defined in `02_ui_ux_specification.md`.

Use Tailwind CSS and reusable design tokens.

Colors, spacing, typography, borders and radii must be defined consistently.

### 13.2. Theme

The initial application theme is dark.

All primary interface components must support the dark theme.

The theme must be applied consistently across:

- Navigation.
- Forms.
- Cards.
- Modals.
- Upload areas.
- Status indicators.
- 3D viewer panels.
- Notifications.

### 13.3. Reusable Components

Create reusable components for common interface elements.

Examples:

- Button.
- Input.
- Card.
- Modal.
- Badge.
- Tooltip.
- Dropdown.
- Toast.
- LoadingSpinner.
- EmptyState.
- ErrorState.

Components must support relevant visual states and accessible interaction.

### 13.4. Icons

Use a consistent icon library such as Lucide React.

Avoid mixing multiple icon libraries.

All icon-only buttons must have accessible labels.

---

## 14. Error Handling and User Feedback

### 14.1. General Error Handling

Implement a centralized strategy for API and application errors.

Errors should be mapped to understandable user messages.

### 14.2. Error Categories

Handle the following categories:

**Authentication Errors**

- Invalid credentials.
- Expired session.
- Access denied.

**Upload Errors**

- Unsupported file format.
- File exceeds maximum size.
- Invalid image.
- Upload interrupted.
- Storage failure.

**Project Errors**

- Project not found.
- Invalid project state.
- Project deletion failure.

**Generation Errors**

- Generation failed.
- Insufficient GPU memory.
- Reconstruction failed.
- Processing service unavailable.
- Task timeout.

**Viewer Errors**

- Result not found.
- Unsupported asset.
- Failed model download.
- Failed GLB parsing.

### 14.3. Notifications

Use toast notifications for short-lived feedback.

Use persistent inline error states for errors that require user attention.

Examples:

- "Проект успешно создан."
- "Изображение успешно загружено."
- "Формат файла не поддерживается."
- "Не удалось загрузить изображение."
- "Обработка завершилась с ошибкой."
- "3D-модель успешно создана."

Do not expose raw exceptions to the user.

### 14.4. Network Failures

The frontend must handle temporary network interruptions.

For read-only requests, TanStack Query may retry failed requests according to a controlled retry policy.

Do not automatically repeat generation, project creation or other non-idempotent operations without backend-supported idempotency.

---

## 15. Security Requirements

### 15.1. Authentication

Do not store authentication secrets in frontend source code or browser local storage.

Use the authentication mechanism defined by the backend.

### 15.2. API Security

All protected API requests must use the configured authentication mechanism.

Do not assume that hiding interface elements provides security.

The backend must validate every protected operation.

### 15.3. File Upload Security

The frontend must perform basic upload validation.

However, file validation on the frontend is not a security boundary.

Never trust file names, MIME types or extensions without backend verification.

### 15.4. Sensitive Data

Do not log:

- Authentication tokens.
- Passwords.
- Private project file URLs.
- Sensitive request data.

### 15.5. User Project Isolation

The frontend must display only projects returned for the currently authenticated user.

Access restrictions must still be enforced by the backend.

---

## 16. Testing Requirements

Use Vitest and React Testing Library for frontend unit and component tests.

Use Playwright for end-to-end testing.

### 16.1. Unit Tests

Test:

- File validation utilities.
- Project status mappings.
- Generation mode mappings.
- Date and file size formatting.
- API error mapping.
- Model and viewer utility functions.

### 16.2. Component Tests

Test:

- Registration form.
- Login form.
- Project cards.
- Project status indicators.
- Image upload component.
- Generation mode selector.
- Processing status component.
- Error notifications.
- Viewer toolbar.

### 16.3. Integration Tests

Test:

- Authentication state initialization.
- Project creation.
- Image uploading.
- Project retrieval.
- Generation initiation.
- Processing status updates.
- Result availability.
- Project deletion.

Use mocked API responses where appropriate.

### 16.4. End-to-End Tests

Implement tests for the main application workflows.

**E2E-01. Registration and Login**

A visitor registers an account and accesses the dashboard.

**E2E-02. Object Generation**

A user creates an object project, uploads one image, starts generation and opens the resulting model.

**E2E-03. Scene Reconstruction**

A user creates a scene project, uploads multiple images, starts reconstruction and opens the resulting scene.

**E2E-04. Failed Generation**

A user sees an appropriate error when processing fails and can retry the operation.

**E2E-05. Project Management**

A user can view, open and delete personal projects.

**E2E-06. Access Control**

An unauthenticated user cannot access protected application pages.

### 16.5. Three.js Tests

Test:

- GLB loading.
- Loading state.
- Invalid model handling.
- Model visibility after loading.
- Camera reset.
- Fit to View.
- Resource cleanup when switching models.

Use lightweight test models for automated testing.

Do not require an actual GPU-based generation pipeline for every frontend test.

---

## 17. Code Quality and Development Standards

### 17.1. TypeScript

Use TypeScript throughout the application.

Avoid `any` whenever practical.

Define explicit types for:

- API requests.
- API responses.
- Domain entities.
- Component props.
- Form data.
- Viewer state.

### 17.2. React Components

Use functional components and React hooks.

Keep components focused on a single responsibility.

Extract reusable logic into custom hooks.

Avoid excessively large components.

### 17.3. Naming Conventions

Use:

- PascalCase for React components.
- camelCase for functions and variables.
- UPPER_SNAKE_CASE for application constants.
- kebab-case for feature directories where appropriate.

### 17.4. Code Formatting

Use ESLint and Prettier.

The application must pass:

- Linting.
- Type checking.
- Production build.

### 17.5. Documentation

Provide a frontend README describing:

- Development setup.
- Environment variables.
- Available scripts.
- Build commands.
- Testing commands.
- Docker execution.

---

## 18. Development Scripts

Provide the following npm scripts:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "eslint .",
    "typecheck": "tsc --noEmit",
    "test": "vitest",
    "test:run": "vitest run",
    "test:e2e": "playwright test"
  }
}
```

Adjust the scripts to match the final TypeScript configuration.

The production build must complete without TypeScript errors.

---

## 19. Acceptance Criteria

### FE-AC-01. Application Initialization

The frontend starts successfully using the configured Vite development environment.

### FE-AC-02. Routing

All required application routes are accessible and correctly rendered.

### FE-AC-03. Protected Routes

Unauthenticated users are redirected when attempting to access protected pages.

### FE-AC-04. API Integration

The frontend successfully communicates with the FastAPI backend through the centralized API client.

### FE-AC-05. Authentication

Users can register, log in and log out.

### FE-AC-06. Dashboard

The dashboard displays the current user's projects and their statuses.

### FE-AC-07. Project Creation

The user can select a generation mode and create a project.

### FE-AC-08. Image Upload

The frontend supports one-image and multiple-image upload workflows.

### FE-AC-09. Image Validation

Invalid images are rejected before upload, and the backend remains the authoritative validator.

### FE-AC-10. Upload Feedback

The interface displays upload progress and upload errors.

### FE-AC-11. Generation Initiation

The frontend can initiate object generation and scene reconstruction through the backend API.

### FE-AC-12. Task Tracking

The frontend correctly tracks asynchronous task statuses and stops polling after a terminal status.

### FE-AC-13. Error Handling

The frontend correctly displays authentication, validation, network and processing errors.

### FE-AC-14. GLB Viewer

The frontend can load and display valid GLB assets.

### FE-AC-15. Viewer Controls

The user can rotate, zoom, pan and reset the 3D camera.

### FE-AC-16. Model Download

The frontend allows downloading completed GLB assets through the authorized backend interface.

### FE-AC-17. Resource Cleanup

Temporary image preview URLs and model resources are released when no longer required.

### FE-AC-18. Responsive Design

The frontend remains usable on desktop and tablet screen sizes.

### FE-AC-19. Code Quality

The application passes linting, type checking and production build.

### FE-AC-20. Docker Integration

The frontend can run as part of the complete Docker Compose application.

---

## 20. Implementation Order

Implement the frontend incrementally.

### Phase 1. Initial Setup

- Initialize React + TypeScript + Vite.
- Configure Tailwind CSS.
- Configure React Router.
- Configure ESLint and Prettier.
- Create the initial directory structure.
- Configure environment variables.

### Phase 2. Application Shell

- Implement AppProviders.
- Implement application layout.
- Implement Sidebar.
- Implement Topbar.
- Configure routing.
- Implement protected routes.

### Phase 3. Authentication

- Implement registration.
- Implement login.
- Implement logout.
- Implement current-user loading.
- Add authentication state handling.

### Phase 4. Project Management

- Implement dashboard.
- Implement project cards.
- Implement empty states.
- Implement project creation.
- Implement project details.
- Implement project deletion.

### Phase 5. Image Upload

- Implement ImageDropzone.
- Add single-image upload.
- Add multiple-image upload.
- Add preview management.
- Add client-side validation.
- Add upload progress and error handling.

### Phase 6. Generation Workflows

- Implement object generation initiation.
- Implement scene reconstruction initiation.
- Implement task status polling.
- Implement pending, processing, completed and failed states.
- Implement retry actions.

### Phase 7. 3D Viewer

- Integrate Three.js and React Three Fiber.
- Implement GLB loading.
- Implement camera controls.
- Implement model centering.
- Implement viewer toolbar.
- Implement loading and error states.
- Implement resource cleanup.

### Phase 8. Quality and Stabilization

- Implement responsive styling.
- Complete component tests.
- Complete integration tests.
- Implement main E2E scenarios.
- Resolve TypeScript and linting errors.
- Verify production build.
- Verify Docker deployment.

---

## 21. Related Specifications

This document defines frontend architecture and implementation requirements.

Related documents:

- `00_project_overview.md` — overall project context.
- `01_product_requirements.md` — product functionality.
- `02_ui_ux_specification.md` — interface and user experience.
- `04_backend_specification.md` — backend architecture and API.
- `05_database_specification.md` — persistence model.
- `06_object_generation.md` — object generation.
- `07_scene_reconstruction.md` — scene reconstruction.
- `08_infrastructure.md` — deployment and infrastructure.
- `09_testing.md` — overall system testing.
- `10_development_roadmap.md` — implementation roadmap.
- `AI_DEVELOPMENT_GUIDE.md` — development workflow, quality gates and agent rules.

Frontend implementation must remain consistent with the API contracts defined in `architecture/api_contracts.md`.