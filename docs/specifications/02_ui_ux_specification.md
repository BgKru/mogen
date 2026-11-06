# 02 — UI/UX Specification

## 1. Document Purpose

This document defines the visual design, user interface structure and interaction patterns of the 3D generation web application.

It describes:
- Application navigation and layout.
- Page structure.
- User interaction flows.
- UI components.
- Design system.
- Visual representation of generation processes.
- 3D viewer interface.
- Responsive behavior.
- UI states and feedback.
- Accessibility requirements.

The purpose of this specification is to ensure a consistent and intuitive user experience across the entire application.

This document describes WHAT the interface should look like and HOW users interact with it.

Frontend implementation details are defined in `03_frontend_specification.md`.

---

## 2. Design Direction

### 2.1. General Design Concept

Create a modern web application focused on AI-powered 3D content generation.

The visual design should combine the aesthetics of professional 3D software with the simplicity of modern SaaS applications.

The primary design direction:

- Dark theme.
- Minimalistic interface.
- Clean typography.
- Subtle borders and shadows.
- Carefully selected accent colors.
- Large visual workspace.
- Clear information hierarchy.
- Minimal unnecessary decorative elements.

The interface should feel like a professional creative tool rather than a generic administration dashboard.

### 2.2. Visual References

Consider the following products as design references:

- Meshy AI — https://www.meshy.ai
- Tripo AI — https://www.tripo3d.ai
- Spline — https://spline.design
- Blender — https://www.blender.org

Use these products as visual inspiration only. Do not copy their interfaces directly.

The final interface should maintain a consistent visual identity.

### 2.3. Color Palette

Use a dark neutral color palette.

Suggested colors:

| Element | Color | Value |
|---|---|---|
| Main background | Deep charcoal | #101116 |
| Sidebar background | Dark gray | #15171D |
| Card background | Surface gray | #1B1E26 |
| Elevated surface | Light charcoal | #222631 |
| Primary accent | Violet | #8B7CFF |
| Secondary accent | Blue | #647CFF |
| Primary text | Off-white | #F4F5F7 |
| Secondary text | Gray | #969BAA |
| Border | Dark gray | #2B2F3A |
| Success | Green | #39B980 |
| Warning | Amber | #E5AA52 |
| Error | Red | #E45D6A |

Colors should be defined through reusable design tokens rather than duplicated throughout components.

Accent colors should be used primarily for important actions, active navigation elements and interactive states.

### 2.4. Typography

Use a modern sans-serif typeface.

Recommended options:

- Inter.
- Geist.
- Manrope.

Typography hierarchy:

| Element | Suggested size |
|---|---:|
| Main page heading | 28–32 px |
| Section heading | 20–24 px |
| Card heading | 16–18 px |
| Body text | 14–16 px |
| Secondary text | 12–14 px |
| Button text | 14 px |
| Small labels | 12 px |

Use consistent font weights and line heights.

Avoid excessive font size variation.

### 2.5. Layout Principles

- Use consistent spacing throughout the application.
- Prefer reusable layout components.
- Maintain sufficient whitespace between sections.
- Use cards and panels to group related information.
- Avoid unnecessary visual decoration.
- Maintain clear separation between navigation, content and contextual actions.
- Keep the main content area visually dominant.

Use an 8px-based spacing system.

Suggested border radii:

- Small controls: 6px.
- Buttons: 8px.
- Cards: 12px.
- Modals: 16px.

---

## 3. Application Layout

### 3.1. General Structure

Authenticated application pages should use a consistent application shell.

The shell consists of:

1. Sidebar navigation.
2. Top navigation bar.
3. Main content area.

### 3.2. Sidebar Navigation

The sidebar should be positioned on the left side of the application.

Suggested desktop width: 240px.

Required elements:

- Application logo and name.
- Dashboard navigation item.
- Create Project navigation item.
- User profile section.
- Logout action.

Navigation items:

| Item | Description |
|---|---|
| Dashboard | Opens the project dashboard |
| Create Project | Starts a new project creation workflow |

The active navigation item must have a visually distinct state.

The sidebar should remain consistent across authenticated pages.

On smaller screens, the sidebar should collapse into a compact navigation menu.

### 3.3. Top Navigation Bar

The top bar should contain:

- Current page title or breadcrumb navigation.
- Contextual actions when applicable.
- User profile or account menu.

The top bar should have a consistent height of approximately 64px.

### 3.4. Main Content Area

The main content area should occupy the remaining available screen space.

Recommended maximum content width: 1440px.

Use flexible layouts that adapt to the available viewport.

3D viewer pages may use the entire available workspace without a restrictive content width.

---

## 4. Application Pages

## 4.1. Landing Page

Route: `/`

Purpose: introduce the application and provide access to registration and authentication.

### Structure

**Hero Section**

Display:
- Application name.
- Main heading explaining the product.
- Short description.
- Primary CTA: Get Started.
- Secondary CTA: Learn More.
- Visual representation of generated 3D content.

Suggested main message:

"Turn Your Photos Into 3D Worlds"

Supporting text:

"Generate detailed 3D objects and reconstruct entire environments from photographs using computer vision and AI."

**Features Section**

Present the two main application capabilities.

Object Generation:
- Upload one photograph.
- Generate an individual 3D model.
- Preview and download the result.

Scene Reconstruction:
- Upload multiple photographs.
- Reconstruct an entire environment.
- Explore the generated 3D scene.

**How It Works Section**

Present the main workflow:

1. Upload photographs.
2. Process images.
3. Generate 3D content.
4. Explore and download the result.

**Footer**

Include basic application information and navigation links.

The landing page should remain simple and visually focused.

---

## 4.2. Registration Page

Route: `/register`

Purpose: allow new users to create an account.

### Layout

Use a centered authentication card.

Required elements:

- Application logo.
- Page heading.
- Email input.
- Password input.
- Password confirmation input.
- Registration button.
- Link to the login page.

### Interaction

- Validate required fields.
- Validate email format.
- Display password requirements.
- Display validation errors.
- Disable the submit button during submission.
- Display a clear success or failure message.

Do not redirect users before registration has actually succeeded.

---

## 4.3. Login Page

Route: `/login`

Purpose: authenticate existing users.

### Required Elements

- Application logo.
- Page heading.
- Email input.
- Password input.
- Login button.
- Link to registration.

### Interaction

- Validate input fields.
- Display authentication errors.
- Show loading state during authentication.
- Redirect successfully authenticated users to the dashboard.

---

## 4.4. Project Dashboard

Route: `/dashboard`

Purpose: provide an overview of the user's projects and quick access to project creation.

Project status and result availability must be displayed independently.

A project may display FAILED status while still having
a previously generated 3D asset available.

### Header

Display:

- Page title: My Projects.
- Short description.
- Primary button: Create Project.

### Project List

Display projects as cards in a responsive grid.

Recommended desktop layout: 3 columns.

Each project card should contain:

- Project preview or placeholder.
- Project name.
- Generation type.
- Creation date.
- Current processing status.
- Action to open the project.
- Contextual menu with a delete action.

### Project Card Types

Object Generation projects should use an object-related icon or preview.

Scene Reconstruction projects should use an environment-related icon or preview.

Completed projects may display a thumbnail of the generated result if one is available.

Do not use random images as previews of actual generated content.

### Project Status Indicators

Display readable status labels:

| Internal status | UI label |
|---|---|
| CREATED | Created |
| UPLOADING | Uploading |
| PENDING | Waiting |
| PROCESSING | Processing |
| COMPLETED | Completed |
| FAILED | Failed |

Use appropriate visual indicators:

- Neutral gray for created and pending.
- Blue or violet for processing.
- Green for completed.
- Red for failed.

Do not communicate status using color alone. Always include a text label.

### Empty State

When the user has no projects, display:

- An illustrative empty state.
- A heading explaining that no projects exist.
- Short supporting text.
- A Create Project button.

Suggested message:

"No projects yet"

"Start by uploading a photograph of an object or several photographs of a location."

---

## 4.5. Project Creation Page

Route: `/projects/new`

Purpose: allow the user to select a generation mode, specify the project name and upload photographs.

Project creation and image uploading are separate backend operations.

The frontend must first create the project and then upload its images.

If one or more uploads fail, the project must remain available
in CREATED state with successfully uploaded images preserved.

The user must be able to return to the project and retry failed uploads.

### Page Structure

The page should contain:

1. Page header.
2. Project name input.
3. Generation mode selection.
4. Image upload area.
5. Generation-specific instructions.
6. Action buttons.

### Generation Mode Selection

Display two large selectable cards.

**Card 1: Object Generation**

Description:

"Generate a 3D model from a single photograph."

Visual elements:
- Object-related illustration.
- Mode name.
- Short description.
- Single-image indicator.

**Card 2: Scene Reconstruction**

Description:

"Reconstruct a 3D environment from multiple photographs."

Visual elements:
- Environment-related illustration.
- Mode name.
- Short description.
- Multiple-images indicator.

The selected card must have a clear active state.

The upload interface must change depending on the selected mode.

### Project Name

Provide a text input for the project name.

The input should have a default suggested value, which the user can modify.

Example:

"My 3D Project"

### Object Image Upload

The upload area should support:

- Drag and drop.
- File selection through the system dialog.
- JPEG and PNG formats.

Display:

- Upload icon.
- Short upload instruction.
- Supported formats.
- Maximum file size.
- Image preview after upload.
- Image removal control.

Only one image is allowed.

### Scene Image Upload

The upload area should support multiple image files.

Display:

- Drag-and-drop area.
- File selection control.
- Number of uploaded images.
- Upload progress where available.
- Image previews in a grid.
- Individual image removal controls.
- Maximum number of supported images.

Provide an expandable information panel:

"Tips for better reconstruction"

Include the following recommendations:

1. Photograph the same location from multiple viewpoints.
2. Maintain sufficient overlap between adjacent photographs.
3. Avoid blurry photographs.
4. Use consistent lighting conditions.
5. Capture as much of the environment as possible.
6. Avoid moving objects during photography.

Explain that successful reconstruction depends on image quality and camera coverage.

### Image Preview

Uploaded images should be displayed as thumbnails.

Each thumbnail should have:

- Image preview.
- Filename.
- Upload status where applicable.
- Remove action.

The user should be able to inspect and remove images before project creation.

### Page Actions

Primary action:

"Create Project"

Secondary action:

"Cancel"

The Create Project button must be disabled when required fields are invalid or uploads are incomplete.

After successful project creation, redirect the user to the project details page.

Project creation must not automatically start generation.

---

## 4.6. Project Details Page

Route: `/projects/{id}`

Purpose: display project information, manage source photographs and control generation.

### Header

Display:

- Project name.
- Generation type.
- Creation date.
- Current status.
- Back to Projects navigation.

Provide a contextual project menu with a delete action.

### Source Images Section

Display all uploaded photographs.

For Object Generation:
- Display the single source photograph.

For Scene Reconstruction:
- Display the entire image collection.

Images should remain accessible for inspection.

### Generation Section

Display a generation panel with:

- Generation type.
- Description of the selected processing method.
- Number of input photographs.
- Short processing information.

When generation has not started, display a primary button:

"Generate 3D Model"

or

"Reconstruct 3D Scene"

Before starting, provide a clear indication of which operation will be performed.

### Processing State

When the task is pending or running, replace the generation button with a processing panel.

Display:

- Current status.
- Processing indicator.
- Current processing stage if available.
- Informative message.

For scene reconstruction, possible processing stages include:

1. Image preparation.
2. Feature extraction and matching.
3. Camera estimation.
4. Dense reconstruction.
5. Mesh generation.
6. Texture generation.
7. Asset export.

Only display stages actually reported by the backend.

Do not fabricate progress percentages or claim that a specific stage has completed without confirmation.

### Completed State

When generation succeeds:

- Display a success indicator.
- Display a result preview if available.
- Provide a "View 3D Model" button.
- Provide a download action.

### Failed State

When generation fails:

- Display a failure indicator.
- Provide a user-friendly explanation.
- Provide a Retry button when retry is available.
- Preserve access to the original photographs.

Technical error details may be displayed in an expandable diagnostic section when appropriate.

If the latest generation attempt fails but a previous successful
result exists:

- Display the latest generation error.
- Keep the previous result accessible.
- Provide a button to open the previous 3D model.
- Keep the previous result download action available.
- Do not replace the previous result with an error placeholder.

---

## 4.7. 3D Result Page

Route: `/projects/{id}/result`

Purpose: provide a dedicated workspace for viewing and downloading generated 3D assets.

This page is one of the most important parts of the application.

The 3D model must be the primary visual element.

The result page must display the current successful GenerationResult,
not necessarily the result of the latest generation task.

A failed regeneration attempt must not make a previously successful
result unavailable.

### Layout

Use a workspace layout:

- Main 3D viewport.
- Compact viewer toolbar.
- Project information panel.
- Download action.

The viewport should occupy most of the available screen.

On desktop, the project information panel may be displayed on the right side.

On smaller screens, the information panel should become collapsible.

### 3D Viewport

The viewport should display the generated asset using Three.js.

Required controls:

- Rotate.
- Zoom.
- Pan.
- Reset camera.
- Fit model to view.

The viewer should support:

- GLB/GLTF loading.
- Textures.
- Materials.
- Lighting.
- Automatic model centering.
- Appropriate initial camera positioning.

Display a neutral background with sufficient contrast against the model.

A subtle grid or ground plane may be used where appropriate.

The default viewer should avoid unnecessary editor features.

### Viewer Toolbar

Include:

- Reset camera.
- Fit to view.
- Optional grid toggle.
- Optional background toggle.
- Fullscreen mode when supported.

Controls should have tooltips.

### Project Information Panel

Display:

- Project name.
- Generation mode.
- Creation date.
- Generation status.
- Number of source images.
- Model file format.
- File size when available.

### Download Action

Provide a prominent Download button.

The primary download format is GLB.

Do not display download actions for unavailable or incomplete assets.

### Viewer States

**Loading**

Display a loading indicator while the 3D asset is being loaded.

**Loaded**

Display the model and enable viewer controls.

**Error**

Display a readable error message when the asset cannot be loaded.

Provide a retry action where appropriate.

**Empty**

If no valid generated asset exists, redirect the user to the project details page or display an appropriate explanation.

---

## 5. Navigation and User Flows

### 5.1. Main Navigation Flow

Guest:

Landing Page -> Registration / Login

Authenticated user:

Dashboard -> Create Project -> Project Details -> Generation -> Result Viewer

### 5.2. Object Generation Flow

Dashboard
-> Create Project
-> Select Object Generation
-> Enter Project Name
-> Upload One Image
-> Create Project
-> Project Details
-> Start Generation
-> Processing
-> Completed
-> 3D Result Viewer
-> Download GLB

### 5.3. Scene Reconstruction Flow

Dashboard
-> Create Project
-> Select Scene Reconstruction
-> Enter Project Name
-> Upload Multiple Images
-> Review Images
-> Create Project
-> Project Details
-> Start Reconstruction
-> Processing
-> Completed
-> 3D Result Viewer
-> Download GLB

### 5.4. Failed Generation Flow

Project Details
-> Start Generation
-> Processing
-> Failed
-> Display Error
-> Retry
-> Processing
-> Completed or Failed

All navigation actions should preserve the project context.

If a previous successful result exists, the user must retain access
to that result after a failed retry.

---

## 6. Reusable UI Components

The interface must use reusable components to maintain visual consistency.

Suggested component library:

### Layout Components

- AppLayout
- Sidebar
- Topbar
- PageContainer
- PageHeader
- ContentSection

### Project Components

- ProjectCard
- ProjectGrid
- ProjectStatusBadge
- ProjectTypeBadge
- EmptyProjectsState
- ProjectActionsMenu

### Upload Components

- ImageDropzone
- ImagePreview
- ImagePreviewGrid
- UploadProgress
- UploadError
- ImageUploadGuidelines

### Generation Components

- GenerationModeCard
- GenerationPanel
- ProcessingIndicator
- ProcessingStageList
- GenerationError
- GenerationSuccess

### Viewer Components

- ModelViewer
- ViewerToolbar
- ViewerLoading
- ViewerError
- ModelInformationPanel
- DownloadButton

### General Components

- Button
- Input
- Select
- Modal
- Tooltip
- Dropdown
- ToastNotification
- ConfirmationDialog
- LoadingSpinner

Use a consistent component API and visual behavior.

Avoid creating multiple components with nearly identical functionality.

---

## 7. Interaction States

All interactive components must provide visual feedback.

### 7.1. Buttons

Support the following states:

- Default.
- Hover.
- Active.
- Focus.
- Disabled.
- Loading.

Primary actions should use the primary accent color.

Secondary actions should use neutral styling.

Destructive actions should use warning or error styling.

### 7.2. Inputs

Support:

- Empty.
- Focused.
- Filled.
- Invalid.
- Disabled.

Validation messages should appear close to the corresponding input.

### 7.3. Upload Areas

Support:

- Empty.
- Drag over.
- Uploading.
- Uploaded.
- Invalid file.
- Upload failed.

### 7.4. Project Cards

Support:

- Default.
- Hover.
- Selected where applicable.
- Processing.
- Completed.
- Failed.

### 7.5. Modals and Dialogs

Use confirmation dialogs for destructive operations.

For example, deleting a project must require confirmation.

Dialogs should clearly explain the consequences of the action.

---

## 8. Notifications and Feedback

Use toast notifications for short-lived application feedback.

Examples:

- Project created successfully.
- Image uploaded successfully.
- File format is not supported.
- Project deleted.
- Failed to upload image.
- Generation task started.
- Model downloaded.

Long-running generation status should be displayed in the project interface rather than relying only on toast notifications.

Errors should include an actionable explanation whenever possible.

Avoid displaying raw backend exceptions.

---

## 9. Responsive Design

The application must adapt to different viewport sizes.

### 9.1. Desktop

Primary target.

Requirements:

- Full sidebar navigation.
- Multi-column project grid.
- Spacious upload areas.
- Large 3D viewport.
- Optional project information panel.

### 9.2. Tablet

Requirements:

- Collapsible sidebar.
- Reduced project grid columns.
- Responsive upload grid.
- Adapted 3D viewport controls.
- Collapsible information panels.

### 9.3. Mobile

Mobile support is desirable for the MVP.

Requirements:

- Compact navigation.
- Single-column layouts.
- Touch-friendly controls.
- Responsive forms.
- Image previews adapted to narrow screens.

The 3D viewer should retain basic interaction capabilities.

Do not prioritize complex desktop-style editing controls on mobile.

---

## 10. Accessibility

The application should follow basic WCAG accessibility principles.

Requirements:

- Sufficient text contrast.
- Visible keyboard focus.
- Keyboard-accessible navigation.
- Accessible labels for form controls.
- Descriptive error messages.
- Alternative text for meaningful images.
- Tooltips or accessible labels for icon-only buttons.
- Do not communicate status through color alone.
- Respect reduced-motion preferences.

All essential operations must remain available without relying exclusively on mouse interaction.

---

## 11. UI Content and Localization

The primary MVP interface language is Russian.

All user-facing text should be stored separately from component logic where practical.

Use consistent terminology:

| Concept | Russian UI label |
|---|---|
| Object Generation | Генерация объекта |
| Scene Reconstruction | Реконструкция сцены |
| Project | Проект |
| Upload Images | Загрузить изображения |
| Generate 3D Model | Создать 3D-модель |
| Reconstruct Scene | Реконструировать сцену |
| Processing | Обработка |
| Completed | Завершено |
| Failed | Ошибка |
| Download | Скачать |
| View 3D Model | Просмотреть 3D-модель |

The interface should be structured so that additional languages can be introduced in the future.

Do not mix Russian and English in user-facing messages unless a technical term has no suitable translation.

---

## 12. UX Constraints

The following principles must be respected:

1. Do not overload pages with unnecessary controls.
2. Keep the primary action clearly visible.
3. Do not display technical details unless they help the user.
4. Do not show fabricated processing percentages.
5. Do not display placeholders as actual generated results.
6. Clearly distinguish Object Generation and Scene Reconstruction.
7. Preserve uploaded images when generation fails.
8. Require confirmation for destructive actions.
9. Do not make completed functionality appear available when its result is missing.
10. Keep the 3D viewer as the main focus of the result page.

---

## 13. Acceptance Criteria

### UI-AC-01. Navigation

The user can navigate between all required pages without broken links or missing application states.

### UI-AC-02. Dashboard

The dashboard correctly displays existing projects and their current statuses.

The empty state is displayed when no projects exist.

### UI-AC-03. Project Creation

The user can select either Object Generation or Scene Reconstruction.

The selected mode determines the upload interface.

### UI-AC-04. Object Upload

The interface allows one image to be uploaded and previewed.

### UI-AC-05. Scene Upload

The interface allows multiple images to be uploaded, previewed and removed.

### UI-AC-06. Input Validation

The interface displays clear validation messages and prevents submission when required information is missing or invalid.

### UI-AC-07. Project Details

The details page displays project information, uploaded images and the appropriate generation controls.

### UI-AC-08. Processing Feedback

The interface displays pending, processing, completed and failed states correctly.

### UI-AC-09. Result Viewer

A completed GLB asset can be opened and viewed in the browser.

### UI-AC-10. Viewer Controls

The user can rotate, zoom, pan and reset the camera.

### UI-AC-11. Download

The user can download the generated model from the result page.

### UI-AC-12. Responsive Layout

The interface remains usable on desktop and tablet viewport sizes.

### UI-AC-13. Consistent Design

All pages use consistent typography, colors, spacing and interactive states.

### UI-AC-14. Error Handling

Upload, generation and loading errors are communicated in a user-friendly manner.

---

## 14. Related Specifications

This document defines the user interface and user experience requirements.

Related documents:

- `00_project_overview.md`
- `01_product_requirements.md`
- `03_frontend_specification.md`
- `04_backend_specification.md`
- `09_testing.md`
- `AI_DEVELOPMENT_GUIDE.md`

The Frontend Specification must implement the layouts, components and interactions defined in this document.

The Product Requirements Specification defines the functional behavior that these interfaces must support.