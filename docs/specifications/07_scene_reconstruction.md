# 07 — Scene Reconstruction Specification

## 1. Document Purpose

This document defines the architecture and implementation requirements for reconstructing complete 3D environments from multiple photographs using photogrammetry.

It describes:

- Photogrammetry processing architecture.
- Input image requirements.
- COLMAP integration.
- Structure-from-Motion (SfM).
- Camera pose estimation.
- Sparse point cloud reconstruction.
- OpenMVS integration.
- Dense point cloud reconstruction.
- Mesh generation and refinement.
- Texture generation.
- GLB export.
- Reconstruction validation.
- Background worker integration.
- Resource management.
- Error handling.
- Testing and acceptance criteria.

This specification covers Scene Reconstruction only.

Individual 3D object generation is defined in `06_object_generation.md`.

The implementation must follow the product requirements in `01_product_requirements.md` and backend architecture in `04_backend_specification.md`.

---

## 2. Overview

### 2.1. Objective

Implement an automated photogrammetry pipeline capable of reconstructing a physical environment from a collection of photographs captured from different viewpoints.

The primary goal is to generate a textured 3D representation of a room, interior, exterior location or another relatively static environment.

The application must allow users to upload multiple photographs, initiate reconstruction, monitor processing and visualize the resulting scene in a browser.

### 2.2. Selected Technologies

Use the following technologies:

| Technology | Responsibility |
|---|---|
| COLMAP | Feature extraction, image matching, camera estimation and sparse reconstruction |
| OpenMVS | Dense reconstruction, mesh generation, mesh refinement and texturing |
| Python | Pipeline orchestration |
| Celery | Background task execution |
| Redis | Background task message broker |
| PostgreSQL | Persistent task and project metadata |
| File Storage | Images, intermediate files and generated assets |
| Three.js | Browser-based 3D visualization |

Official resources:

COLMAP:
- Documentation: https://colmap.github.io/
- CLI: https://colmap.github.io/cli.html
- GitHub: https://github.com/colmap/colmap

OpenMVS:
- GitHub: https://github.com/cdcseacave/openMVS
- Usage documentation: https://github.com/cdcseacave/openMVS/blob/develop/docs/wiki/Usage.md
- Build documentation: https://github.com/cdcseacave/openMVS/blob/develop/docs/wiki/Building.md

### 2.3. Input

The reconstruction pipeline accepts:

- A collection of JPEG or PNG photographs.
- Project identifier.
- Generation task identifier.
- Reconstruction configuration.

All photographs must represent the same physical environment.

Photographs should capture the environment from multiple overlapping viewpoints.

### 2.4. Output

The primary output is a textured 3D scene in GLB format.

The output must contain:

- Polygonal mesh geometry.
- UV coordinates where applicable.
- Texture images.
- Materials.
- Scene transformations.
- Valid glTF-compatible data.

The generated asset must be suitable for loading through Three.js.

### 2.5. Reconstruction Limitations

Photogrammetry reconstructs geometry from visual information present in photographs.

It cannot reliably recover:

- Surfaces that are never visible in the input images.
- Completely textureless surfaces.
- Geometry hidden behind objects.
- Accurate geometry of transparent materials.
- Reliable geometry of highly reflective surfaces.
- Objects that move significantly between photographs.

The resulting reconstruction represents the visible environment rather than a complete semantic understanding of the physical location.

### 2.6. Scene Representation

For the MVP, the resulting scene may consist of one large textured mesh or several meshes.

The system does not need to identify individual furniture items, walls or other semantic objects.

Semantic object segmentation and independent editing of reconstructed objects are outside the MVP scope.

---

## 3. Reconstruction Architecture

### 3.1. General Architecture

Scene reconstruction must execute inside an isolated background worker.

The FastAPI server must not directly execute COLMAP or OpenMVS commands.

Logical components:

1. FastAPI — receives reconstruction requests.
2. PostgreSQL — stores project and task information.
3. Redis — distributes background tasks.
4. Celery — manages task execution.
5. Scene Worker — executes the reconstruction pipeline.
6. COLMAP — performs camera estimation and sparse reconstruction.
7. OpenMVS — reconstructs dense geometry and textures.
8. File Storage — stores all source images and generated assets.

### 3.2. Processing Flow

```text
Frontend
   |
   | POST /projects/{id}/generate
   v
FastAPI
   |
   v
Generation Service
   |
   +---------> PostgreSQL
   |            Create GenerationTask
   |            Update Project Status
   |
   v
Celery
   |
   v
Redis
   |
   v
Scene Reconstruction Worker
   |
   v
Prepare Input Dataset
   |
   v
COLMAP
   |
   +-------------------------+
   |                         |
   v                         |
Feature Extraction           |
   |                         |
   v                         |
Feature Matching             |
   |                         |
   v                         |
Camera Estimation            |
   |                         |
   v                         |
Sparse Reconstruction        |
   |                         |
   +-------------------------+
   |
   v
COLMAP Image Undistortion
   |
   v
OpenMVS InterfaceCOLMAP
   |
   v
OpenMVS DensifyPointCloud
   |
   v
ReconstructMesh
   |
   v
RefineMesh
   |
   v
TextureMesh
   |
   v
TransformScene / GLB Export
   |
   v
Asset Validation
   |
   v
File Storage
   |
   v
PostgreSQL Result Metadata
   |
   v
Project Status: COMPLETED
```

### 3.3. Architectural Requirements

- COLMAP and OpenMVS must execute outside FastAPI request handlers.
- Each reconstruction task must use an isolated working directory.
- Workers must operate only on images associated with the current generation task.
- Intermediate processing results must be stored in task-specific directories.
- Reconstruction stages must execute in the correct order.
- A failed processing stage must prevent subsequent dependent stages from running.
- All external commands must be executed with controlled arguments and timeouts.
- The worker must persist stage information and errors.
- The final asset must be validated before successful task completion.

### 3.4. Worker Environment

Create a separate environment for the scene reconstruction pipeline.

Do not require the main FastAPI environment to install COLMAP, OpenMVS or their native dependencies.

Recommended directory structure:

```text
ml/
│
├── scene_reconstruction/
│   ├── __init__.py
│   │
│   ├── config.py
│   ├── pipeline.py
│   ├── dataset.py
│   ├── preflight.py
│   ├── colmap_runner.py
│   ├── reconstruction_selector.py
│   ├── openmvs_runner.py
│   ├── mesh_processor.py
│   ├── exporter.py
│   ├── validator.py
│   ├── diagnostics.py
│   └── exceptions.py
│
├── workers/
│   ├── celery_app.py
│   ├── scene_tasks.py
│   └── worker_health.py
│
├── requirements-scene.txt
└── README.md
```

COLMAP and OpenMVS should preferably be available as command-line executables inside the dedicated worker container.

The Python orchestration layer must manage their execution.

---

## 4. Input Image Requirements

### 4.1. Supported Formats

The pipeline must accept:

- JPEG / JPG.
- PNG.

Unsupported files must be rejected before reconstruction starts.

### 4.2. Number of Photographs

Initial MVP configuration:

```env
MIN_SCENE_IMAGES=3
MAX_SCENE_IMAGES=100
```

These are configurable application limits.

Three images are only the minimum upload threshold, not a guarantee of successful reconstruction.

The optimal number of photographs depends on:

- Environment size.
- Geometric complexity.
- Camera movement.
- Image resolution.
- Visual overlap.
- Hardware capabilities.

More images do not automatically guarantee better reconstruction and can significantly increase processing time.

### 4.3. Photograph Characteristics

The application should recommend the following capture conditions:

**Camera movement**

Photographs should be captured from different physical positions.

Rotating the camera from approximately the same position without changing its location is insufficient for reliable 3D reconstruction.

**Visual overlap**

Adjacent photographs should contain substantial overlapping visual information.

Important scene features should be visible in several photographs.

As a practical recommendation, important objects should appear in at least three views.

**Lighting**

Capture photographs under similar lighting conditions.

Avoid:

- Strongly changing illumination.
- High dynamic range conditions.
- Direct sunlight causing severe shadows.
- Strong reflections.
- Excessive exposure differences.

**Surface characteristics**

Prefer textured environments.

Completely white walls, uniform surfaces and transparent materials may produce insufficient visual features.

**Image quality**

Avoid:

- Motion blur.
- Excessive noise.
- Low resolution.
- Severe compression artifacts.
- Extreme perspective distortion.

### 4.4. Camera Movement

The preferred capture method is to move the camera around the environment while maintaining overlapping coverage.

For interior reconstruction:

1. Capture the main environment from multiple positions.
2. Move around the perimeter.
3. Capture additional views of important surfaces.
4. Include overlapping views of adjacent areas.
5. Avoid sudden changes in lighting and camera zoom.

### 4.5. Input Validation

Before processing, validate:

- File extension.
- Actual image format.
- File decodability.
- Image dimensions.
- File size.
- Number of photographs.
- Image uniqueness.

Exact duplicates should be detected using SHA-256 checksums.

Near-duplicate detection may be implemented as an optional preprocessing improvement.

### 4.6. Image Metadata

Preserve the original image files and available EXIF information.

Camera metadata may provide useful information for camera initialization and focal length estimation.

Do not unnecessarily re-encode uploaded images before COLMAP processing.

If image orientation normalization is required, ensure that the camera metadata remains consistent with the transformed image.

### 4.7. Input Dataset Preparation

Copy or link the task's source image snapshot into an isolated working directory.

Recommended structure:

```text
working/scene/{task_id}/
│
├── images/
│   ├── image_001.jpg
│   ├── image_002.jpg
│   ├── image_003.jpg
│   └── ...
│
├── colmap/
│
├── openmvs/
│
├── output/
│
└── logs/
```

The working directory must be isolated from other tasks.

The original files in project storage must remain unchanged.

### 4.8. Preflight Validation

Before running COLMAP, perform preliminary checks:

- Required number of images is available.
- All files can be decoded.
- No exact duplicate files exist.
- Image dimensions are within configured limits.
- Files are accessible to the worker.
- Sufficient storage space is available.

Image blur, exposure and feature richness checks may be used to warn about potentially problematic photographs.

These heuristic checks must not guarantee successful reconstruction.

### 4.9. User Guidance

The frontend must display capture recommendations before users start scene reconstruction.

The minimum upload count must not be presented as a guarantee of successful photogrammetry.

---

## 5. COLMAP Integration

### 5.1. Responsibilities

COLMAP is responsible for the Structure-from-Motion stage.

Its responsibilities include:

- Feature extraction.
- Feature matching.
- Geometric verification.
- Camera intrinsic estimation.
- Camera pose estimation.
- Sparse point cloud reconstruction.
- Bundle adjustment.
- Image undistortion.

The output is a sparse 3D reconstruction with camera parameters and registered images.

### 5.2. Processing Pipeline

The MVP must use the following COLMAP sequence:

```text
1. Feature Extraction
       |
       v
2. Feature Matching
       |
       v
3. Sparse Reconstruction
       |
       v
4. Reconstruction Selection
       |
       v
5. Image Undistortion
```

### 5.3. Workspace Structure

Prepare a COLMAP workspace:

```text
colmap/
│
├── database.db
│
├── sparse/
│   └── 0/
│
└── dense/
```

The actual sparse model directory must be selected based on the reconstruction results.

Do not assume that `sparse/0` always contains a valid reconstruction.

---

## 6. Feature Extraction

### 6.1. Objective

Detect distinctive visual features in the uploaded photographs.

These features will be used to identify corresponding locations between different camera views.

### 6.2. Technology

Use the COLMAP `feature_extractor` command.

Command example:

```bash
colmap feature_extractor \
    --database_path database.db \
    --image_path images
```

### 6.3. Responsibilities

The feature extraction stage must:

- Load input photographs.
- Detect local image features.
- Compute feature descriptors.
- Store features in the COLMAP database.
- Preserve camera information where available.

### 6.4. Configuration

Important parameters should be configurable:

- Maximum number of features.
- Camera model.
- Camera grouping policy.
- GPU usage.
- Image dimensions.

Use sensible defaults and pin the COLMAP version.

Avoid introducing experimental feature extractors in the initial MVP without separate quality evaluation.

### 6.5. Output Validation

Verify:

- Feature extraction completed successfully.
- The COLMAP database exists.
- Expected photographs were processed.
- The database contains usable feature information.

If the input images produce insufficient features, record an appropriate diagnostic.

---

## 7. Feature Matching

### 7.1. Objective

Identify corresponding visual features between photographs.

Matching information is required for estimating relative camera positions and reconstructing scene geometry.

### 7.2. Matching Strategy

Use COLMAP matchers.

Recommended strategies:

**Exhaustive Matcher**

Suitable for relatively small unordered collections of photographs.

Every possible image pair is considered.

**Sequential Matcher**

Suitable for photographs captured in a meaningful sequence with substantial overlap between neighboring images.

For the MVP:

- Use Exhaustive Matcher as the default for unordered image collections.
- Allow Sequential Matcher as a configurable alternative when capture order is reliable.
- Select matching configuration based on the expected capture workflow.

### 7.3. Exhaustive Matching Command

```bash
colmap exhaustive_matcher \
    --database_path database.db
```

### 7.4. Sequential Matching Command

```bash
colmap sequential_matcher \
    --database_path database.db
```

### 7.5. Geometric Verification

COLMAP performs geometric verification of image matches.

The system must use geometrically verified correspondences during reconstruction.

### 7.6. Validation

Verify:

- Matching process completed.
- Database contains verified image pairs.
- Sufficient image connectivity exists.
- The dataset is not fragmented into unrelated groups.

If no meaningful correspondences exist, the task must fail before dense reconstruction.

---

## 8. Sparse Reconstruction and Camera Estimation

### 8.1. Objective

Recover camera positions and initial sparse 3D geometry.

### 8.2. Technology

Use the COLMAP `mapper` command.

Example:

```bash
mkdir -p sparse

colmap mapper \
    --database_path database.db \
    --image_path images \
    --output_path sparse
```

### 8.3. Reconstruction Process

COLMAP performs incremental Structure-from-Motion.

The general process includes:

1. Selecting initial image pairs.
2. Registering cameras.
3. Triangulating 3D points.
4. Adding additional images.
5. Estimating camera poses.
6. Performing bundle adjustment.
7. Refining camera parameters and sparse geometry.

### 8.4. Output

A successful reconstruction must contain:

- Camera models.
- Registered image information.
- Camera poses.
- Sparse 3D points.
- Feature tracks and observations.

### 8.5. Multiple Sparse Models

COLMAP may produce multiple reconstruction models.

The implementation must inspect all generated candidates.

Do not automatically select the first output directory.

Implement a reconstruction selection strategy based on:

- Number of registered images.
- Fraction of successfully registered images.
- Number of reconstructed 3D points.
- Camera pose validity.
- Available reconstruction quality metrics.

Prefer the candidate that provides the most useful coherent reconstruction rather than relying on directory order alone.

When multiple disconnected components represent different parts of the input environment, the system must report that the reconstruction may be incomplete.

For the MVP, do not automatically merge unrelated components using arbitrary transformations.

The selected sparse reconstruction must be validated against the immutable image snapshot of the current task.

The worker must store the selected reconstruction model identifier and its diagnostic metrics.

Reconstruction quality warnings must not automatically be treated as fatal errors unless configured acceptance thresholds are violated.

### 8.6. Reconstruction Validation

Before continuing:

- At least one valid sparse model must exist.
- Camera parameters must be valid.
- Registered image count must be sufficient.
- The point cloud must contain meaningful geometry.
- Camera poses must contain finite values.

The system should calculate and record:

- Total input image count.
- Registered image count.
- Registration ratio.
- Number of 3D points.
- Available reprojection error statistics.
- Reconstruction component count.

Use configurable quality thresholds based on testing.

Do not assume that a fixed number of registered images guarantees a usable reconstruction.

### 8.7. Failure Conditions

Possible failure conditions:

- No images registered.
- Too few registered images.
- Insufficient matching correspondences.
- Invalid camera parameters.
- Empty sparse point cloud.
- Severely fragmented reconstruction.

When reconstruction fails, do not start dense reconstruction.

Record available diagnostic information and mark the task as FAILED.

---

## 9. Image Undistortion

### 9.1. Objective

Prepare registered images and camera parameters for Multi-View Stereo processing.

### 9.2. Technology

Use the COLMAP `image_undistorter` command.

Example:

```bash
mkdir -p dense

colmap image_undistorter \
    --image_path images \
    --input_path sparse/0 \
    --output_path dense \
    --output_type COLMAP \
    --max_image_size 2000
```

The selected sparse reconstruction path must replace `sparse/0` in the actual pipeline.

### 9.3. Responsibilities

The undistortion stage must:

- Undistort registered images.
- Generate the corresponding camera parameters.
- Prepare the dense workspace.
- Preserve the relationship between image files and camera data.
- Limit image resolution where configured.

### 9.4. Output

The dense workspace must contain the data required for OpenMVS import.

Typical structure:

```text
dense/
│
├── images/
├── sparse/
└── ...
```

### 9.5. Validation

Verify:

- Undistorted photographs exist.
- Camera parameters are available.
- The sparse model is present.
- Image references are valid.
- OpenMVS-compatible input data can be created.

---

## 10. OpenMVS Integration

### 10.1. Responsibilities

OpenMVS is responsible for Multi-View Stereo reconstruction and final surface generation.

Its responsibilities include:

- Importing COLMAP reconstruction data.
- Dense point cloud generation.
- Mesh reconstruction.
- Mesh refinement.
- Texture mapping.
- GLB-compatible export.

### 10.2. Processing Pipeline

The MVP must use the following sequence:

```text
COLMAP Reconstruction
       |
       v
InterfaceCOLMAP
       |
       v
OpenMVS Scene (.mvs)
       |
       v
DensifyPointCloud
       |
       v
ReconstructMesh
       |
       v
RefineMesh
       |
       v
TextureMesh
       |
       v
TransformScene
       |
       v
GLB
```

Each stage must be implemented as a separate, observable processing step.

### 10.3. Import COLMAP Reconstruction

Use the OpenMVS `InterfaceCOLMAP` executable.

Command example:

```bash
InterfaceCOLMAP \
    -i dense \
    -o scene.mvs \
    --image-folder dense/images
```

The input directory must contain the undistorted COLMAP camera data and corresponding sparse reconstruction.

### 10.4. Import Validation

Verify:

- `scene.mvs` is generated.
- Camera information is present.
- Registered image references are valid.
- Sparse point cloud information is available.
- Image paths resolve correctly.

If import fails, stop the pipeline.

### 10.5. Dense Reconstruction

Use OpenMVS `DensifyPointCloud`.

Command:

```bash
DensifyPointCloud scene.mvs
```

The command generates a dense point cloud and associated dense scene data.

OpenMVS uses Multi-View Stereo techniques, including PatchMatch-based depth estimation in the default workflow.

### 10.6. Dense Reconstruction Responsibilities

The stage must:

- Estimate depth maps.
- Estimate surface normals.
- Fuse depth information from multiple views.
- Generate a dense point cloud.
- Preserve available camera and image associations.

### 10.7. Dense Reconstruction Validation

Verify:

- Dense reconstruction completes.
- Dense point cloud is available.
- The point cloud contains non-empty geometry.
- Coordinates are finite.
- The result is suitable for mesh reconstruction.

Possible failure conditions:

- Insufficient camera overlap.
- Invalid depth maps.
- Memory exhaustion.
- CUDA failure.
- Insufficient disk space.
- Invalid scene configuration.

### 10.8. Mesh Reconstruction

Use OpenMVS `ReconstructMesh`.

Example:

```bash
ReconstructMesh scene_dense.mvs \
    -p scene_dense.ply
```

This stage generates a polygonal surface from the dense point cloud.

### 10.9. Mesh Validation

Verify:

- Mesh file exists.
- Mesh contains vertices.
- Mesh contains valid faces.
- Geometry contains finite coordinates.
- Bounding box dimensions are positive.
- The resulting surface is usable for further refinement.

An empty or severely degenerate mesh must not proceed to texturing.

### 10.10. Mesh Refinement

Use OpenMVS `RefineMesh`.

Example:

```bash
RefineMesh scene_dense.mvs \
    -m scene_dense_mesh.ply \
    -o scene_dense_mesh_refined.mvs
```

Mesh refinement improves the reconstructed surface using available image and geometric information.

This stage should help recover surface details and improve the mesh representation.

The exact refinement parameters must be evaluated on representative datasets.

For the initial MVP:

- Enable the standard refinement stage.
- Use conservative settings.
- Make expensive refinement options configurable.
- Allow refinement to be disabled for diagnostic or low-resource execution profiles.

### 10.11. Texture Generation

Use OpenMVS `TextureMesh`.

Example:

```bash
TextureMesh scene_dense.mvs \
    -m scene_dense_mesh_refined.ply \
    -o scene_dense_mesh_refined_texture.mvs
```

Texture generation must:

- Project reconstructed mesh faces into available camera images.
- Select appropriate source views.
- Generate UV coordinates.
- Construct texture atlases.
- Associate textures with mesh materials.

The texture generation step is required for the final MVP scene quality.

Post-MVP increment 14 adds an optional, disabled-by-default post-reconstruction
enhancement substage after `RefineMesh`/`TextureMesh` (see
[`../additions/14_mesh_texture_enhancement.md`](../additions/14_mesh_texture_enhancement.md)).
It never repeats those OpenMVS stages, never regenerates OpenMVS UVs/atlases by
default, and preserves multi-mesh transforms, material assignments and embedded
texture references. When it is disabled (the default), the existing scene output
and validation path is unchanged.

### 10.12. Texture Validation

Verify:

- The textured mesh exists.
- UV coordinates are available where expected.
- Material references are valid.
- Texture images are generated.
- The resulting scene can be exported without missing texture references.

Surfaces not visible in source photographs may have missing or unreliable texture information.

Do not claim that the entire reconstructed environment is accurately textured if visible regions remain incomplete.

---

## 11. GLB Export

### 11.1. Primary Format

The primary output format is GLB.

OpenMVS provides support for GLB/glTF export through its scene transformation and export utilities.

### 11.2. Export Tool

Use the OpenMVS `TransformScene` executable for automated conversion.

Illustrative command:

```bash
TransformScene scene_dense_mesh_refined_texture.mvs \
    --convert 1 \
    --export-type glb
```

The exact output filename must be verified against the pinned OpenMVS build.

Do not assume that the command succeeds solely because the process exits without reporting an error.

The exact TransformScene command-line arguments must be verified against the pinned OpenMVS version before implementation.

Before integrating the exporter into the application:

1. Execute `TransformScene --help` in the final worker image.
2. Verify the supported GLB export options.
3. Perform a standalone textured scene export.
4. Verify the actual output file path.
5. Validate the generated GLB with an independent glTF validator.
6. Load the result using Three.js GLTFLoader.

The verified command and expected output artifacts must be documented in the final implementation.

The OpenMVS exporter does not embed the texture image. It writes the mesh into the GLB with embedded buffers but references the texture as a sidecar file, so a GLB produced directly by OpenMVS is normally a two-file asset rather than a single-file GLB.

Consequences for the pipeline:

- A repack stage is mandatory. The exported scene, or the OBJ/MTL/PNG set OpenMVS also writes, must be loaded and re-exported as a single-file GLB with embedded buffers and images, using the pinned conversion library.
- The repack stage must verify that the result contains no external image references (`images[].uri`), exactly one embedded buffer, and at least one mesh primitive with texture coordinates.
- OpenMVS emits the `KHR_materials_unlit` extension. Three.js maps that extension to an unlit material, so the model renders without lighting response. If lit rendering is required, the material must be converted after loading, and that viewer decision must be recorded.
- The repack stage is an independently identifiable stage. If it fails, the task must be marked `FAILED` with `GLB_EXPORT_FAILED` or `GLB_VALIDATION_FAILED`; an incomplete asset must never be registered as a result.

The pinned OpenMVS build and conversion library versions are recorded in `architecture/phase0_decisions.md`.

This is a mandatory check, not a formality: the chosen OpenMVS version, together with the repack stage, must be proven to produce a standalone GLB with embedded textures before it becomes part of the pipeline.

### 11.3. Export Requirements

The generated GLB must contain:

- Mesh geometry.
- Material definitions.
- Texture images.
- UV information.
- Required scene transformations.

The GLB must be self-contained, with embedded textures, as required by Section 11.2.

The output must not depend on temporary worker directories or external image paths.

### 11.4. Output Naming

Use task-specific unique names.

Example:

```text
projects/{project_id}/results/{task_id}/scene.glb
```

Do not overwrite previous successfully generated scene assets.

### 11.5. Scale and Orientation

Photogrammetric reconstruction without known physical reference dimensions generally does not provide guaranteed metric scale.

The resulting scene may have:

- Arbitrary scale.
- An arbitrary coordinate origin.
- An orientation that does not match the real-world vertical direction.

For the MVP:

- Preserve the reconstructed relative geometry.
- Do not claim metric accuracy.
- Record that dimensions are relative unless a known scale has been applied.
- Use automatic viewer centering and camera fitting.
- Do not apply undocumented geometry transformations during export.

Metric scaling, georeferencing and automatic floor-plane alignment are future improvements.

---

## 12. Reconstruction Quality and Diagnostics

### 12.1. Objective

Provide useful information about reconstruction quality and failures.

A successful program exit code does not necessarily mean that a usable scene has been generated.

### 12.2. Quality Metrics

Where available, record:

**Input metrics**

- Total uploaded image count.
- Image dimensions.
- Unique image count.
- Available camera metadata.

**Sparse reconstruction metrics**

- Registered image count.
- Registration ratio.
- Number of 3D points.
- Reprojection error statistics.
- Reconstruction component count.

**Dense reconstruction metrics**

- Dense point cloud size.
- Number of reconstructed points.
- Mesh vertex count.
- Mesh face count.
- Texture count.

**Output metrics**

- GLB file size.
- Bounding box dimensions.
- Number of meshes.
- Material count.
- Texture availability.
- Validation status.

These metrics should be stored as optional result metadata.

### 12.3. Quality Warnings

The application may display warnings for:

- Low camera registration ratio.
- Insufficient reconstructed points.
- Disconnected reconstruction components.
- Missing texture regions.
- Excessive mesh complexity.
- Incomplete coverage.

Quality warnings must not be confused with fatal processing errors.

### 12.4. Reconstruction Completeness

The system should distinguish:

- Processing failure.
- Successful reconstruction with warnings.
- Successful reconstruction without detected warnings.

Do not introduce an artificial quality score without a defined and validated calculation methodology.

### 12.5. Diagnostic Artifacts

Where appropriate, preserve:

- COLMAP sparse reconstruction.
- Camera registration report.
- Dense point cloud.
- Intermediate mesh.
- OpenMVS log files.
- Processing configuration.

These files may be retained for debugging according to the storage retention policy.

They are not necessarily downloadable by regular users in the MVP.

---

## 13. Celery Integration

### 13.1. Task Definition

Create a dedicated Celery task:

`reconstruct_scene_task`

The task must receive identifiers rather than image payloads.

Example:

```python
reconstruct_scene_task.delay(
    project_id=str(project_id),
    task_id=str(task_id),
)
```

### 13.2. Task Execution

The worker must:

1. Retrieve the generation task.
2. Verify that the task is PENDING.
3. Verify that the project exists and is not deleted.
4. Retrieve the immutable source image snapshot.
5. Validate image availability.
6. Create an isolated working directory.
7. Update task and project status to PROCESSING.
8. Execute image preflight validation.
9. Execute COLMAP feature extraction.
10. Execute feature matching.
11. Execute sparse reconstruction.
12. Select and validate the sparse model.
13. Execute image undistortion.
14. Import the reconstruction into OpenMVS.
15. Execute dense reconstruction.
16. Generate the polygonal mesh.
17. Refine the mesh.
18. Generate textures.
19. Export GLB.
20. Report RESULT_VALIDATION and validate the final asset.
21. Store the generated scene.
22. Register GenerationResult.
23. Update task and project status to COMPLETED.

The worker must stop immediately when a mandatory pipeline stage fails.

### 13.3. Processing Stages

Use the following persistent stage identifiers:

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

Not every stage must expose an accurate percentage.

Persist the current stage in the GenerationTask record.

`COMPLETED`, `FAILED` and `CANCELLED` are task states, not processing stages. They must not be written to the stage field.

### 13.4. Progress Reporting

Progress must be based on actual processing information.

The initial MVP may display stage-based progress without percentages.

For example:

```text
Image preparation: Completed
Feature extraction: Completed
Feature matching: Completed
Sparse reconstruction: In progress
```

The frontend must not display fabricated completion percentages.

### 13.5. Task Idempotency

Each generation task must have its own working directory.

Do not reuse intermediate outputs belonging to another task.

If a task is restarted:

- Inspect the task status.
- Inspect previously generated intermediate files.
- Validate intermediate artifacts before reuse.
- Restart invalid or incomplete stages.
- Never treat an unvalidated GLB as a completed result.

### 13.6. Checkpointing

The pipeline should preserve completed intermediate stages.

Example:

```text
working/scene/{task_id}/
│
├── colmap/
│   ├── database.db
│   ├── sparse/
│   └── dense/
│
├── openmvs/
│   ├── scene.mvs
│   ├── scene_dense.mvs
│   ├── scene_dense_mesh.ply
│   └── scene_dense_mesh_refined_texture.mvs
│
├── output/
│   └── scene.glb
│
└── logs/
```

A restarted worker may reuse completed stages only after verifying the existence and integrity of their outputs.

Prefer restarting a failed stage over trusting partially written intermediate files.

### 13.7. Worker Failure Recovery

Handle:

- Worker termination.
- COLMAP process termination.
- OpenMVS process termination.
- CUDA errors.
- RAM exhaustion.
- Disk exhaustion.
- Redis interruption.
- Database interruption.
- Task timeout.

Stale PROCESSING tasks must be detectable through heartbeat information, lease expiration and recovery procedures.

Do not mark a task COMPLETED merely because a previous process created an output file.

Final result validation is mandatory.

---

## 14. External Process Execution

### 14.1. General Requirements

COLMAP and OpenMVS must be executed through controlled subprocess management.

Use Python `subprocess` or an equivalent process management abstraction.

### 14.2. Command Execution

Requirements:

- Use argument arrays rather than shell command strings.
- Set an explicit working directory.
- Configure execution timeouts.
- Capture standard output.
- Capture standard error.
- Record process exit codes.
- Terminate dependent processes after unrecoverable failures.
- Preserve logs for diagnostics.

Avoid using `shell=True` with user-controlled values.

Example:

```python
import subprocess
from pathlib import Path

def run_command(
    command: list[str],
    workdir: Path,
    timeout: int,
) -> subprocess.CompletedProcess:

    return subprocess.run(
        command,
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
```

The implementation must additionally handle:

- TimeoutExpired.
- CalledProcessError.
- Missing executables.
- Process termination.
- Log persistence.

### 14.3. Process Isolation

Each generation task must have:

- Its own process working directory.
- Its own intermediate files.
- Its own logs.
- Its own timeout configuration.

Do not allow concurrent tasks to write to the same directories.

### 14.4. Configuration

Command-line options must be built from validated configuration values.

Do not construct arbitrary command parameters from frontend input.

### 14.5. Cancellation

The processing architecture should support task cancellation in a controlled manner.

A cancellation operation must:

- Stop the currently running reconstruction process.
- Terminate dependent child processes.
- Prevent further pipeline stages from executing.
- Mark task state consistently.
- Preserve diagnostic logs where possible.
- Clean up incomplete temporary outputs according to retention rules.

Full user-facing cancellation controls are optional for the MVP.

---

## 15. Performance and Resource Management

### 15.1. General Requirements

Scene reconstruction can consume significant CPU, memory, GPU memory and disk space.

The pipeline must use configurable resource limits.

The Scene Worker must verify available disk space and memory before starting resource-intensive processing stages.

Temporary processing data must be isolated by generation task.

Resource exhaustion must result in a controlled task failure with the corresponding diagnostic information.

### 15.2. COLMAP Resources

COLMAP may use:

- CPU for feature extraction and matching.
- CUDA for supported GPU operations.
- CPU and GPU resources for dense reconstruction when those COLMAP stages are used.

The initial pipeline uses COLMAP primarily for sparse reconstruction and camera estimation.

### 15.3. OpenMVS Resources

OpenMVS uses CPU resources and can optionally use CUDA-accelerated processing depending on its build configuration.

Its principal resource-intensive stages include:

- Dense depth estimation.
- Depth-map fusion.
- Mesh reconstruction.
- Mesh refinement.
- Texture generation.

GPU acceleration is optional and must not be assumed to be available.

### 15.4. Worker Concurrency

For the MVP:

- Start with one active scene reconstruction task per worker.
- Make concurrency configurable.
- Do not run several large dense reconstruction jobs on a single machine without resource testing.
- Separate scene workers from TripoSR workers.
- Monitor disk and memory consumption.

### 15.5. Image Resolution

COLMAP image undistortion supports maximum image size configuration.

Use a configurable maximum processing resolution.

Initial development default:

```env
SCENE_MAX_IMAGE_SIZE=2000
```

This value should be evaluated against reconstruction quality and hardware requirements.

Do not permanently discard the original image resolution from project storage.

### 15.6. Large Scenes

Large datasets may exceed available memory during dense reconstruction or mesh generation.

OpenMVS provides a scalable processing script capable of dividing large scenes into sub-scenes when necessary.

Potential utility:

`MvsScalablePipeline.py`

It should not be mandatory for the initial implementation.

The scalable pipeline may introduce seams where sub-scenes meet.

For the MVP:

- Start with the standard OpenMVS pipeline.
- Add optional memory-aware scene splitting.
- Enable it only after validation on representative datasets.
- Record whether scene splitting was used.

### 15.7. Disk Management

Before processing, verify available working storage.

Intermediate reconstruction files may be considerably larger than the uploaded photographs.

The worker must:

- Track temporary storage usage.
- Handle insufficient disk space.
- Remove obsolete intermediate files safely.
- Preserve final generated assets.
- Avoid cleaning directories still used by active tasks.

### 15.8. Performance Metrics

Record:

- Input preparation duration.
- COLMAP feature extraction duration.
- Matching duration.
- Sparse reconstruction duration.
- Image undistortion duration.
- OpenMVS import duration.
- Dense reconstruction duration.
- Mesh reconstruction duration.
- Mesh refinement duration.
- Texture generation duration.
- GLB export duration.
- Total processing duration.
- Peak memory usage where available.

Do not promise a fixed processing time.

Performance depends on dataset complexity and available hardware.

---

## 16. Configuration

All reconstruction parameters must be configurable.

Example environment configuration:

```env
SCENE_RECONSTRUCTION_ENABLED=true

SCENE_MIN_IMAGES=3
SCENE_MAX_IMAGES=100

SCENE_MATCHING_STRATEGY=EXHAUSTIVE

SCENE_MAX_IMAGE_SIZE=2000

SCENE_COLMAP_USE_GPU=true
SCENE_COLMAP_MAX_FEATURES=8192

SCENE_OPENMVS_USE_CUDA=false

SCENE_MAX_THREADS=4
SCENE_WORKER_CONCURRENCY=1

SCENE_MAX_TASK_TIME_SECONDS=14400

SCENE_ENABLE_MESH_REFINEMENT=true
SCENE_ENABLE_TEXTURE_GENERATION=true

SCENE_OUTPUT_FORMAT=GLB

SCENE_ENABLE_SCALABLE_PIPELINE=false
```

These values are initial development settings, not guaranteed optimal values.

The implementation must validate the configuration and adapt it to the actual COLMAP and OpenMVS builds.

Maintain explicit paths for:

- COLMAP executable.
- OpenMVS executable directory.
- Shared storage root.
- Task working directory.
- Temporary directory.

Do not hardcode machine-specific executable paths.

---

## 17. Error Handling

### 17.1. Error Categories

Use stable error codes.

| Error Code | Description |
|---|---|
| INSUFFICIENT_IMAGES | Not enough source photographs |
| IMAGE_DECODE_FAILED | Image cannot be decoded |
| DUPLICATE_IMAGES | Exact duplicate photographs detected |
| INVALID_SCENE_DATASET | Invalid input dataset |
| FEATURE_EXTRACTION_FAILED | COLMAP feature extraction failed |
| FEATURE_MATCHING_FAILED | COLMAP matching failed |
| NO_VALID_MATCHES | No usable geometric matches |
| SPARSE_RECONSTRUCTION_FAILED | Sparse reconstruction failed |
| INSUFFICIENT_REGISTERED_IMAGES | Too few images registered |
| INVALID_CAMERA_PARAMETERS | Invalid camera data |
| IMAGE_UNDISTORTION_FAILED | Undistortion failed |
| OPENMVS_IMPORT_FAILED | COLMAP scene import failed |
| DENSE_RECONSTRUCTION_FAILED | Dense reconstruction failed |
| INSUFFICIENT_DENSE_POINTS | Dense point cloud is insufficient |
| MESH_GENERATION_FAILED | Mesh reconstruction failed |
| MESH_REFINEMENT_FAILED | Mesh refinement failed |
| TEXTURE_GENERATION_FAILED | Texture generation failed |
| GLB_EXPORT_FAILED | GLB export failed |
| GLB_VALIDATION_FAILED | Exported GLB is invalid |
| INSUFFICIENT_STORAGE | Insufficient working storage |
| MEMORY_LIMIT_EXCEEDED | Processing exceeded memory limits |
| CUDA_EXECUTION_FAILED | CUDA processing error |
| TOOL_TIMEOUT | External process exceeded its timeout |
| EXTERNAL_TOOL_UNAVAILABLE | Required executable is unavailable |

### 17.2. Failure Handling

When a mandatory stage fails:

- Stop subsequent processing.
- Record the failed stage.
- Record a stable error code.
- Store the user-friendly message.
- Preserve relevant worker logs.
- Mark the task as FAILED.
- Update project status if this is still the latest active task.
- Clean up incomplete outputs when safe.

### 17.3. Previous Results

A failed reconstruction attempt must not remove a previously generated successful scene.

The previous current GenerationResult must remain available.

### 17.4. Diagnostic Information

Internal logs may contain:

- Command execution details.
- Tool versions.
- Return codes.
- Standard error output.
- Reconstruction metrics.
- Resource measurements.

These details must not be returned directly through ordinary frontend API responses.

---

## 18. GLB Output Validation

### 18.1. General Requirements

The final generated scene must be validated before registration as a successful result.

### 18.2. Validation Pipeline

```text
GLB Export
    |
    v
File Exists
    |
    v
File Size Check
    |
    v
GLB Container Validation
    |
    v
glTF Structure Validation
    |
    v
Mesh Validation
    |
    v
Material Validation
    |
    v
Texture Reference Validation
    |
    v
Geometry Bounds Validation
    |
    v
Checksum Calculation
    |
    v
Validated Scene
```

### 18.3. Mandatory Checks

Verify:

- The output file exists.
- The output file is not empty.
- The GLB container is valid.
- The glTF version and asset structure are supported.
- At least one mesh exists.
- Mesh geometry is not empty.
- Vertex coordinates contain finite values.
- Face indices are valid.
- Bounding box dimensions are positive.
- Material references are valid.
- Referenced textures are available.
- The asset can be parsed by a compatible glTF library.
- The file checksum can be calculated.

### 18.4. Texture Checks

When texturing is enabled:

- Verify the presence of texture data.
- Verify UV attributes where applicable.
- Verify material-to-texture references.
- Verify that the asset does not reference missing external files.

The primary result should be self-contained GLB.

### 18.5. Validation Failure

If mandatory checks fail:

- Do not create a GenerationResult.
- Mark the task as FAILED.
- Record the validation failure.
- Preserve diagnostic artifacts as configured.

---

## 19. Integration with the Application

### 19.1. Backend Integration

Integrate the pipeline with the interfaces defined in the backend specification.

Implement:

`PhotogrammetryReconstructor`

The implementation must expose a high-level reconstruction operation without leaking COLMAP and OpenMVS internal execution details into the business service layer.

### 19.2. Task Integration

The scene worker must use the existing persistent task system.

Required relationships:

- Project.
- GenerationTask.
- GenerationTaskImage.
- GenerationResult.

### 19.3. Task Input

The worker must retrieve source images using the immutable image snapshot associated with the generation task.

Do not retrieve an arbitrary current image list from the project when processing a historical task.

### 19.4. Result Persistence

After successful export:

1. Validate the GLB.
2. Move the asset to its final storage location.
3. Calculate its checksum and file size.
4. Persist result metadata.
5. Update the task status.
6. Update the project status.
7. Mark the new result as current.

All database updates related to result registration must be performed transactionally.

### 19.5. Frontend Compatibility

The resulting GLB must be compatible with the frontend viewer specified in `03_frontend_specification.md`.

The backend must provide:

- Result metadata.
- Model file size.
- Model format.
- Authorized download endpoint.
- Result availability status.

---

## 20. Testing Requirements

### 20.1. Unit Tests

Test individual processing modules:

- Dataset preparation.
- Image validation.
- Duplicate detection.
- COLMAP command construction.
- Reconstruction selection.
- OpenMVS command construction.
- Processing stage transitions.
- GLB validation.
- Result metadata generation.
- Error mapping.

### 20.2. Integration Tests

Test:

- COLMAP feature extraction.
- COLMAP feature matching.
- Sparse reconstruction.
- Camera estimation.
- Image undistortion.
- OpenMVS COLMAP import.
- Dense reconstruction.
- Mesh generation.
- Mesh refinement.
- Texture generation.
- GLB export.

### 20.3. Test Datasets

Prepare several representative datasets:

**Dataset A — Small Interior**

A small room photographed from several positions.

Purpose:
- Validate the complete pipeline.
- Test basic scene reconstruction.
- Validate textured mesh export.

**Dataset B — Complex Interior**

A room with furniture, different surface materials and multiple visible objects.

Purpose:
- Evaluate reconstruction completeness.
- Identify texture and geometric errors.

**Dataset C — Exterior Environment**

A small outdoor environment.

Purpose:
- Evaluate camera movement.
- Validate reconstruction in different lighting conditions.

**Dataset D — Poor Quality Images**

A dataset containing:

- Blurry images.
- Low-texture surfaces.
- Insufficient overlap.
- Different exposure conditions.

Purpose:
- Evaluate failure detection.
- Verify error reporting.
- Ensure invalid reconstructions are not marked as successful.

### 20.4. Quality Evaluation

Evaluate results using:

- Number of registered images.
- Registration ratio.
- Number of reconstructed points.
- Mesh completeness.
- Visual geometry quality.
- Texture quality.
- Presence of holes and missing surfaces.
- Output file size.
- Browser compatibility.

Where reference geometry is available, use geometric comparison metrics.

Do not rely exclusively on the successful completion of external commands as proof of reconstruction quality.

### 20.5. Performance Tests

Measure:

- Total processing time.
- CPU usage.
- Peak RAM usage.
- GPU usage where applicable.
- Peak VRAM usage.
- Disk consumption.
- Intermediate file sizes.
- Final GLB size.

Repeat measurements with different image counts and image resolutions.

### 20.6. Failure Tests

Verify:

- No COLMAP matches.
- No valid sparse reconstruction.
- Invalid camera parameters.
- OpenMVS import failure.
- Dense reconstruction failure.
- Empty mesh.
- Texture generation failure.
- GLB export failure.
- Insufficient RAM.
- Insufficient GPU memory.
- Insufficient storage.
- External tool timeout.
- Worker interruption.

### 20.7. End-to-End Tests

A complete integration test must:

1. Create a SCENE project.
2. Upload multiple photographs.
3. Start scene reconstruction.
4. Verify asynchronous processing.
5. Retrieve processing status.
6. Wait for task completion within the test's configured timeout.
7. Retrieve the generated GLB.
8. Load the GLB through a compatible glTF library.
9. Verify that the asset contains valid geometry and appearance data.
10. Verify that the result can be displayed by the frontend 3D viewer.

Use a small real-world dataset and actual COLMAP/OpenMVS binaries for at least one end-to-end pipeline test.

Mocked external processes may be used in ordinary API tests.

---

## 21. Acceptance Criteria

### SCENE-AC-01. Worker Initialization

The Scene Worker starts successfully and detects the configured COLMAP and OpenMVS executables.

### SCENE-AC-02. Input Validation

The pipeline accepts valid JPEG and PNG photographs and rejects invalid files.

### SCENE-AC-03. Dataset Preparation

The worker creates an isolated workspace for each reconstruction task.

### SCENE-AC-04. Feature Extraction

COLMAP successfully extracts features from valid source photographs.

### SCENE-AC-05. Feature Matching

COLMAP identifies and geometrically verifies matching features.

### SCENE-AC-06. Sparse Reconstruction

COLMAP produces at least one valid sparse reconstruction.

### SCENE-AC-07. Camera Estimation

The system identifies registered images and valid camera parameters.

### SCENE-AC-08. Sparse Model Selection

The worker selects a valid reconstruction candidate based on measured reconstruction properties.

### SCENE-AC-09. Image Undistortion

The worker creates an OpenMVS-compatible undistorted image workspace.

### SCENE-AC-10. OpenMVS Import

InterfaceCOLMAP successfully imports the COLMAP reconstruction.

### SCENE-AC-11. Dense Reconstruction

OpenMVS generates a valid dense point cloud.

### SCENE-AC-12. Mesh Generation

OpenMVS produces a valid polygonal mesh.

### SCENE-AC-13. Mesh Refinement

The worker can execute the configured mesh refinement stage.

### SCENE-AC-14. Texture Generation

OpenMVS generates a textured mesh with valid material and texture references.

### SCENE-AC-15. GLB Export

The worker exports a valid GLB file using the OpenMVS conversion tools.

### SCENE-AC-16. GLB Validation

The generated GLB passes mandatory structure and geometry validation.

### SCENE-AC-17. Task Status

The backend receives accurate processing stages and terminal task status.

### SCENE-AC-18. Result Persistence

The generated scene is stored in persistent storage and registered in PostgreSQL.

### SCENE-AC-19. Error Handling

Failures in COLMAP, OpenMVS and export stages are correctly recorded.

### SCENE-AC-20. Previous Result Preservation

A failed new reconstruction does not remove an existing successful result.

### SCENE-AC-21. Resource Isolation

Multiple projects do not share temporary processing directories or overwrite one another's files.

### SCENE-AC-22. Browser Compatibility

The generated scene can be loaded and inspected using the application's Three.js viewer.

### SCENE-AC-23. Real Reconstruction

At least one complete scene reconstruction is successfully performed using actual photographs and real COLMAP/OpenMVS processing.

### SCENE-AC-24. Docker Integration

The Scene Worker executes through the configured Docker environment with access to required binaries, storage and processing resources.

---

## 22. Implementation Order

Implement scene reconstruction incrementally.

### Phase 1. Environment Preparation

- Install COLMAP.
- Install OpenMVS.
- Verify binary dependencies.
- Configure CPU processing.
- Verify GPU support where available.
- Pin compatible versions.
- Prepare sample datasets.

### Phase 2. Standalone COLMAP Pipeline

- Implement input dataset preparation.
- Run feature extraction.
- Run feature matching.
- Run sparse reconstruction.
- Select a valid sparse model.
- Perform image undistortion.
- Inspect reconstruction output.

### Phase 3. Standalone OpenMVS Pipeline

- Implement InterfaceCOLMAP import.
- Run DensifyPointCloud.
- Run ReconstructMesh.
- Run RefineMesh.
- Run TextureMesh.
- Inspect intermediate results.

### Phase 4. GLB Export

- Implement TransformScene integration.
- Export GLB.
- Validate mesh geometry.
- Validate texture references.
- Open the model in Three.js.

### Phase 5. Pipeline Orchestration

- Implement PhotogrammetryReconstructor.
- Add processing stages.
- Implement external process management.
- Implement configurable timeouts.
- Add checkpointing.
- Add diagnostic logs.

### Phase 6. Backend Integration

- Implement Celery scene task.
- Retrieve source image snapshots.
- Update task statuses.
- Persist generation results.
- Implement retry handling.
- Implement storage cleanup.

### Phase 7. Performance Optimization

- Test different image resolutions.
- Test different image counts.
- Evaluate matching strategies.
- Adjust worker concurrency.
- Evaluate memory usage.
- Introduce optional scalable reconstruction for large scenes.

### Phase 8. Testing and Stabilization

- Complete unit tests.
- Complete integration tests.
- Execute real reconstruction tests.
- Test malformed datasets.
- Test worker interruptions.
- Verify output quality.
- Verify Docker Compose execution.
- Document deployment requirements.

---

## 23. Licensing and Third-Party Dependencies

Before distributing or deploying the application, review the licenses of all included software and model components.

In particular:

- COLMAP.
- OpenMVS.
- CUDA and related dependencies.
- OpenMVS external dependencies.
- Python packages.

The current official OpenMVS repository identifies its project license as AGPL-3.0.

The legal implications of using, modifying, distributing or operating OpenMVS as part of a network-accessible service must be reviewed before public deployment.

Do not assume that invoking OpenMVS as a separate process automatically removes licensing obligations.

Retain required license notices and documentation.

---

## 24. Related Specifications

This document defines Scene Reconstruction.

Related documents:

- `00_project_overview.md` — overall project architecture.
- `01_product_requirements.md` — scene reconstruction requirements.
- `02_ui_ux_specification.md` — scene creation interface.
- `03_frontend_specification.md` — frontend integration and 3D viewer.
- `04_backend_specification.md` — API and background processing.
- `05_database_specification.md` — task and result persistence.
- `06_object_generation.md` — individual object generation.
- `08_infrastructure.md` — COLMAP/OpenMVS deployment.
- `09_testing.md` — system testing.
- `10_development_roadmap.md` — implementation sequence.
- `architecture/api_contracts.md` — canonical API definitions.
- `AI_DEVELOPMENT_GUIDE.md` — development workflow, quality gates and agent rules.

The complete reconstruction pipeline must be implemented according to this document and the pinned versions of COLMAP and OpenMVS.
---

## Neural representation (increment 15)

An optional, deployment-selected Gaussian-splat representation is specified in
[`../additions/15_neural_scene_reconstruction.md`](../additions/15_neural_scene_reconstruction.md).
COLMAP + OpenMVS remains the default and produces the same GLB contract described
in this document. The neural path reuses the validated COLMAP sparse model and
undistorted images, stops before every OpenMVS stage, registers a Gaussian PLY
as a distinct result representation, and remains unavailable unless the
dedicated neural worker image passes its runtime preflight. Nothing in Section
13 (result persistence) or the existing stage identifiers changes for mesh
reconstructions.
