1. Project Description

Develop a client-server web application for generating 3D models from photographs using computer vision and machine learning technologies.

The application must support two generation modes:

Object Generation — reconstruction of an individual 3D object from a single photograph.

Scene Reconstruction — photogrammetric reconstruction of an entire environment or location from multiple photographs.

The main goal is to simplify 3D content creation and reduce the time required for manual 3D modeling.

The application is inspired by Meshy AI and Tripo AI. Its key differentiator is the ability to reconstruct entire environments in addition to individual objects.

2. Core Technologies

Frontend: React, TypeScript, Vite, Tailwind CSS.

3D Rendering: Three.js, React Three Fiber.

Backend: Python, FastAPI.

Machine Learning: PyTorch.

Object Generation: TripoSR.

Scene Reconstruction: COLMAP, OpenMVS.

Database: PostgreSQL.

ORM: SQLAlchemy.

Background Processing: Celery, Redis.

Infrastructure: Docker, Docker Compose.

3. Core Application Modules

The system consists of the following logical modules:

User Interface — application interface and project management.

Project Management — creation, retrieval and deletion of projects.

Image Management — uploading, validating and storing photographs.

Object Generation — generating individual 3D models using TripoSR.

Scene Reconstruction — reconstructing 3D environments using COLMAP and OpenMVS.

Task Processing — managing asynchronous generation tasks.

3D Viewer — displaying generated models and scenes in the browser.

File Storage — storing source images and generated assets.

4. Generation Workflows

4.1 Object Generation

Input: one photograph in JPEG or PNG format.

Processing:

Validate the uploaded image.

Preprocess the image if necessary.

Run TripoSR.

Convert the generated model into a browser-compatible format.

Store the result.

Output: a downloadable 3D model, primarily in GLB format.

4.2 Scene Reconstruction

Input: multiple photographs of the same physical environment, captured from different viewpoints.

Processing:

Validate uploaded photographs.

Extract image features.

Match corresponding features between photographs.

Estimate camera positions and reconstruct sparse geometry using COLMAP.

Generate dense geometry using COLMAP and OpenMVS.

Reconstruct and refine the mesh.

Generate textures.

Export the final scene.

Output: a textured 3D reconstruction, primarily in GLB format.

5. Architectural Principles

Use a modular client-server architecture.

Separate business logic from machine learning processing.

Keep object generation and scene reconstruction independent.

Use asynchronous background processing for computationally intensive tasks.

Keep frontend and backend communication API-based.

Store metadata in PostgreSQL and binary assets in file storage.

Make ML processing replaceable without changing the core application.

Support future migration of ML workloads to a separate GPU server.

Use consistent naming conventions, data structures and API contracts.

Use PostgreSQL as the authoritative source for persistent application state.

Use Redis exclusively for background message transport and optional caching.

Implement Transactional Outbox for reliable background task dispatch.

Assume at-least-once message delivery and make worker execution idempotent.

Keep generation task history independently from project status.

Preserve previous successful generation results during new processing attempts.

Use immutable source image snapshots for every generation task.

Separate task execution recovery from manual generation retries.

6. MVP Scope

The initial version must provide:

Project creation and management.

Image uploading and validation.

Object generation using TripoSR.

Scene reconstruction using COLMAP and OpenMVS.

Asynchronous processing and status tracking.

Browser-based 3D visualization.

Downloading generated models.

Docker Compose-based deployment.

The following features are outside the initial MVP scope:

Manual editing of 3D geometry.

Semantic segmentation of reconstructed scenes into individual objects.

Collaborative editing.

Real-time multiplayer functionality.

Advanced scene generation using generative AI.

Complex animation and rigging tools.

7. Development Guidelines for AI

When implementing the application:

Always read this document and the relevant subsystem specifications before modifying code.

Follow the architecture and contracts defined in the documentation.

Do not introduce technologies that contradict the established stack without explaining the reason.

Do not implement fake functionality or substitute real ML processing with static results.

Keep components modular and maintain separation of responsibilities.

Avoid unnecessary abstractions and premature optimization.

Implement features incrementally.

Test each completed feature.

Update documentation when implementation changes architectural decisions or API contracts.

Do not modify unrelated modules when implementing an isolated feature.

Follow the workflow, quality gates and reporting rules defined in the AI Development Guide (`AI_DEVELOPMENT_GUIDE.md`) at the documentation root. It governs how implementation work is performed; it does not override the requirements defined in this document or in the subsystem specifications.

8. Specification Priority

In case of conflicting requirements, follow this priority:

Project Overview.

Relevant subsystem specification.

Architecture and API contracts.

Development roadmap.

If a conflict cannot be resolved, report it before implementation.

9. Expected Result

A functional web application that allows users to upload photographs, generate individual 3D objects or reconstruct entire environments, preview results in the browser and download the generated assets.