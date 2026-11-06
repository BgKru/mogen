# 06 — Object Generation Specification

## 1. Document Purpose

This document defines the architecture and implementation requirements for generating individual 3D objects from photographs using TripoSR.

It describes:

- TripoSR model integration.
- ML worker architecture.
- Model initialization and management.
- Input image preparation.
- Background removal.
- Inference execution.
- 3D mesh extraction.
- Model export.
- GLB validation.
- Result storage.
- Task status reporting.
- Error handling.
- GPU resource management.
- Testing and acceptance criteria.

This specification covers only Object Generation.

Scene Reconstruction is defined separately in `07_scene_reconstruction.md`.

---

## 2. Overview

### 2.1. Objective

Implement a backend processing module that generates an individual 3D model from one photograph.

The primary algorithm is TripoSR, an open-source image-to-3D reconstruction model developed by Tripo AI and Stability AI.

Official resources:

- GitHub: https://github.com/VAST-AI-Research/TripoSR
- Model weights: https://huggingface.co/stabilityai/TripoSR
- Research paper: https://arxiv.org/abs/2403.02151

### 2.2. Input

The generation process accepts:

- One JPEG or PNG photograph.
- Project identifier.
- Generation task identifier.
- Generation configuration.

The photograph must represent one clearly visible individual object.

### 2.3. Output

The primary output is a 3D model in GLB format.

The generated asset must contain:

- Mesh geometry.
- Vertex colors or supported material and texture information.
- Valid geometric data.
- A format compatible with the application's Three.js viewer.

The output must be stored in the configured file storage.

### 2.4. Model Characteristics

TripoSR is a feed-forward single-image 3D reconstruction model.

It predicts a plausible 3D representation from one input image without requiring iterative per-object optimization.

The model is based on the Large Reconstruction Model (LRM) architecture.

It reconstructs missing geometry using learned priors rather than actual observations of unseen sides.

This distinction must be reflected in the application's user guidance.

The generated model is an approximation, not a guaranteed geometrically accurate reconstruction of the physical object.

---

## 3. System Architecture

### 3.1. Processing Architecture

Object generation must execute inside a dedicated ML worker.

The FastAPI application must not directly load TripoSR or execute model inference.

Logical components:

1. FastAPI — accepts generation requests.
2. PostgreSQL — stores project and task information.
3. Redis — transports background task messages.
4. Celery — schedules and manages tasks.
5. Object Worker — executes generation.
6. TripoSR — performs image-to-3D inference.
7. File Storage — stores input and generated assets.

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
   +----> PostgreSQL
   |       Create GenerationTask
   |       Update Project Status
   |
   v
Celery Task Dispatch
   |
   v
Redis
   |
   v
Object Generation Worker
   |
   v
Load Source Image
   |
   v
Image Preprocessing
   |
   v
TripoSR Inference
   |
   v
Mesh Extraction
   |
   v
GLB Export
   |
   v
Asset Validation
   |
   v
File Storage
   |
   v
PostgreSQL
   |
   v
Project Status: COMPLETED
```

### 3.3. Architectural Requirements

- Object generation must be isolated from the FastAPI process.
- The model must not be initialized for every HTTP request.
- Workers must process independent generation tasks.
- Workers must not access files belonging to unrelated projects.
- Intermediate files must be stored in task-specific directories.
- All task execution must be associated with a persistent GenerationTask.
- Errors must be reported to the backend through persistent task state.
- The worker must not expose an HTTP endpoint directly to the frontend.

### 3.4. Worker Environment

Create a separate Python environment for TripoSR.

Do not install all TripoSR dependencies into the main FastAPI environment.

The worker must have its own dependency configuration.

Suggested structure:

```text
ml/
│
├── object_generation/
│   ├── __init__.py
│   │
│   ├── config.py
│   ├── model_loader.py
│   ├── generator.py
│   ├── preprocessing.py
│   ├── mesh_processor.py
│   ├── exporter.py
│   ├── validator.py
│   ├── exceptions.py
│   │
│   └── tests/
│
├── workers/
│   ├── celery_app.py
│   ├── object_tasks.py
│   └── worker_health.py
│
├── requirements-object.txt
└── README.md
```

The exact module structure may be adjusted during implementation, but model inference, preprocessing and export must remain separate responsibilities.

---

## 4. TripoSR Integration

### 4.1. Official Implementation

Use the official repository:

https://github.com/VAST-AI-Research/TripoSR

Use the corresponding pretrained weights:

https://huggingface.co/stabilityai/TripoSR

Do not replace the model with a mock, randomly generated mesh or static demonstration asset.

### 4.2. Dependency Management

Install and configure the dependencies required by the official implementation.

Important dependencies include:

- PyTorch.
- CUDA-compatible PyTorch build when using NVIDIA GPUs.
- Pillow.
- NumPy.
- rembg.
- transformers.
- trimesh.
- torchmcubes.
- xatlas.

The final dependency list must be derived from the selected TripoSR repository revision.

### 4.3. Version Pinning

The official repository must be pinned to a specific Git commit.

Model weights must also be associated with a known revision or checksum.

Do not build production images directly from an unpinned moving branch.

The pinned TripoSR commit, the PyTorch and CUDA combination, and the dependency lockfile decision are recorded in `architecture/phase0_decisions.md`.

Maintain the following information:

- TripoSR repository URL.
- Git commit SHA.
- Model checkpoint revision.
- Model weight checksum where available.
- PyTorch version.
- CUDA compatibility information.
- Python version.
- Installed dependency versions.

This makes generation behavior reproducible and simplifies debugging.

### 4.4. Model Loading

Initialize TripoSR inside the Object Worker process.

Recommended behavior:

1. Start the worker.
2. Check the configured processing device.
3. Verify availability of model weights.
4. Load model configuration.
5. Initialize the pretrained model.
6. Move the model to the selected device.
7. Verify model readiness.
8. Accept processing tasks.

The model should remain initialized in worker memory between tasks whenever possible.

Do not reload model weights for every generation request.

### 4.5. Model Cache

Store pretrained weights in a persistent cache.

Do not download model weights every time the worker starts.

Use a dedicated Docker Volume or configured cache directory.

Example:

```text
/data/model-cache/
└── triposr/
    ├── config.yaml
    └── model.ckpt
```

The actual file structure must follow the official model loading implementation.

Model downloads should occur during a controlled initialization or setup process.

The application must not depend on external model downloads during an individual generation task.

---

## 5. Hardware and Resource Requirements

### 5.1. GPU Support

Use PyTorch with CUDA for NVIDIA GPU acceleration.

The worker must check:

- PyTorch availability.
- CUDA availability.
- GPU device visibility.
- Available GPU memory.
- Model compatibility.

### 5.2. VRAM

The official TripoSR README reports approximately 6 GB of VRAM for a single-image input with default settings.

This is a reference value rather than a universal minimum or guaranteed hardware requirement.

Actual memory consumption depends on:

- GPU architecture.
- CUDA and PyTorch versions.
- Model settings.
- Chunk size.
- Memory occupied by other processes.

For the MVP:

- Use GPU processing as the default execution mode.
- Start with conservative worker concurrency.
- Run one generation task at a time per GPU.
- Make the processing configuration adjustable.

### 5.3. CPU Fallback

The official implementation includes CPU execution fallback.

CPU inference may be useful for development or environments without a compatible GPU.

However, CPU processing may be significantly slower.

For the application:

- GPU processing must be the default.
- CPU fallback must be explicitly configurable.
- The application must not silently change to CPU processing when a GPU worker is misconfigured.
- CPU execution must have an appropriate task timeout.

### 5.4. VRAM Optimization

Expose configurable parameters:

- `chunk_size`
- `mc_resolution`
- `device`

A smaller chunk size can reduce GPU memory consumption at the cost of slower processing.

Do not change model resolution or inference parameters unpredictably between tasks.

### 5.5. GPU Memory Management

The worker must:

- Avoid excessive concurrent inference.
- Release intermediate tensors after processing.
- Avoid retaining unused GPU references.
- Handle CUDA out-of-memory errors.
- Monitor worker memory usage.
- Prevent one failed task from permanently blocking subsequent tasks.

Use appropriate PyTorch inference and cleanup mechanisms.

Example:

```python
import gc
import torch

def cleanup_gpu():
    gc.collect()

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
```

Memory cleanup must be performed after releasing all references to temporary tensors and model outputs.

Do not reload the model after every task merely to clear memory.

### 5.6. Resource Isolation

Object Generation and Scene Reconstruction should use separate worker processes.

A memory-intensive scene reconstruction task must not consume all available resources allocated to TripoSR.

---

## 6. Input Image Requirements

### 6.1. Supported Formats

The input image must use one of the following formats:

- JPEG / JPG.
- PNG.

The image must be successfully decoded before preprocessing.

### 6.2. Object Visibility

The photograph should contain:

- One clearly visible main object.
- Sufficient object detail.
- Good lighting.
- Minimal motion blur.
- Limited occlusion.
- A distinguishable object/background boundary.

The object should occupy a meaningful part of the image.

### 6.3. Recommended Photograph Characteristics

The application should guide users to provide photographs that:

- Show the entire object.
- Use a relatively simple background.
- Avoid severe perspective distortion.
- Avoid excessive shadows.
- Avoid strong reflections when possible.
- Avoid multiple overlapping objects.

A single input image does not provide enough information to recover all physical dimensions and hidden surfaces accurately.

### 6.4. Image Validation

Before inference, verify:

- Image format.
- Successful decoding.
- Positive width and height.
- Maximum file size.
- Maximum image dimensions.
- Reasonable aspect ratio.

Invalid files must be rejected before model execution.

### 6.5. Original Image Preservation

Never modify the original uploaded photograph.

Store the original image in Project Storage.

All preprocessing operations must produce separate intermediate files.

This ensures that the user can retry generation without uploading the photograph again.

---

## 7. Image Preprocessing

### 7.1. Objective

Prepare the uploaded photograph for TripoSR inference.

The preprocessing pipeline must improve the representation of the foreground object and normalize the image according to model requirements.

### 7.2. Processing Pipeline

```text
Original Image
     |
     v
Image Decoding
     |
     v
EXIF Orientation Correction
     |
     v
Color Space Normalization
     |
     v
Background Removal
     |
     v
Foreground Cropping and Resizing
     |
     v
Background Compositing
     |
     v
Model Input Image
```

### 7.3. Image Decoding

Use Pillow or an equivalent image-processing library.

Requirements:

- Decode the actual image contents.
- Apply EXIF orientation where present.
- Normalize the image to an RGB/RGBA representation.
- Handle malformed files.
- Avoid unnecessary image quality degradation.

### 7.4. Background Removal

Use the background-removal mechanism provided by the TripoSR pipeline.

The official implementation supports automatic background removal using rembg.

The preprocessing implementation should:

1. Initialize the background-removal session.
2. Generate an alpha mask.
3. Separate the foreground from the background.
4. Preserve the object's visible details.
5. Prepare the image for subsequent resizing.

The background-removal model should not be initialized for every task if it can be safely reused within a worker process.

### 7.5. Foreground Cropping and Resizing

After background removal:

- Determine foreground bounds.
- Crop unnecessary empty space.
- Preserve original object proportions.
- Resize the object to a suitable relative size.
- Avoid cutting off object extremities.

The official default foreground ratio is approximately 0.85.

Treat this as an initial configurable parameter rather than an immutable application requirement.

### 7.6. Background Compositing

Prepare the processed image using a neutral background according to the official inference pipeline.

Do not introduce arbitrary colors that may interfere with object reconstruction.

### 7.7. Preprocessing Output

Save the processed photograph in the task-specific working directory.

Example:

```text
working/object/{task_id}/
├── input/
│   ├── original.jpg
│   └── preprocessed.png
│
└── output/
```

The original image must remain unchanged.

The preprocessed image must be available for debugging failed generation tasks according to the retention policy.

### 7.8. Preprocessing Errors

Possible errors:

- IMAGE_DECODE_FAILED.
- INVALID_IMAGE_DIMENSIONS.
- BACKGROUND_REMOVAL_FAILED.
- INVALID_FOREGROUND_MASK.
- IMAGE_PREPROCESSING_FAILED.

If preprocessing fails, the worker must stop processing and report the corresponding error.

Do not continue inference with an invalid or empty foreground image.

---

## 8. TripoSR Inference

### 8.1. Inference Input

The model receives:

- Preprocessed RGB image.
- Configured inference device.
- Model configuration.
- Reconstruction parameters.

### 8.2. Inference Process

The worker must execute the TripoSR model using the official implementation.

The logical flow:

1. Load the preprocessed image.
2. Convert it into the model's expected input representation.
3. Run the image encoder and reconstruction network.
4. Produce the model's intermediate 3D representation.
5. Extract the reconstructed surface.
6. Return mesh geometry and associated appearance information.

Do not implement a replacement neural network.

### 8.3. Model Execution

Use PyTorch inference mode or the equivalent no-gradient inference context.

Example:

```python
with torch.inference_mode():
    scene_codes = model([image], device=device)
```

The exact invocation must match the pinned TripoSR implementation.

### 8.4. Inference Configuration

The following parameters must be configurable.

| Parameter | Initial Default | Description |
|---|---:|---|
| device | cuda:0 | Processing device |
| chunk_size | 8192 | Evaluation chunk size |
| mc_resolution | 256 | Marching Cubes resolution |
| remove_background | true | Automatic background removal |
| foreground_ratio | 0.85 | Foreground scale in input image |
| output_format | glb | Mesh export format |
| bake_texture | false | Texture atlas generation |

These defaults follow the official implementation where applicable.

Do not expose every technical parameter to the end user in the MVP.

### 8.5. Inference Timeout

Use configurable task timeouts.

Consider:

- Model initialization.
- GPU memory availability.
- Image preprocessing.
- Mesh extraction.
- Export operations.

Do not assume the model's reported inference time represents total application generation time.

### 8.6. Inference Errors

Handle:

- MODEL_LOAD_FAILED.
- GPU_UNAVAILABLE.
- GPU_OUT_OF_MEMORY.
- CUDA_EXECUTION_FAILED.
- MODEL_INFERENCE_FAILED.
- MODEL_TIMEOUT.

Errors must be captured and converted into stable internal error codes.

Do not expose raw CUDA exceptions or stack traces to the frontend.

---

## 9. Mesh Extraction

### 9.1. Objective

Convert the intermediate 3D representation produced by TripoSR into polygonal mesh geometry.

### 9.2. Surface Extraction

Use the mesh extraction mechanism provided by the official model.

The implementation uses a Marching Cubes-based surface extraction process.

The resulting mesh must contain:

- Vertices.
- Faces.
- Vertex normals or data from which normals can be calculated.
- Appearance information.

### 9.3. Mesh Resolution

The reconstruction resolution must be configurable.

The official implementation uses a default Marching Cubes resolution of 256.

For the MVP, use the default unless testing identifies a resource or quality issue.

Higher resolution should not be enabled without evaluating its performance and memory impact.

### 9.4. Mesh Validation

After extraction, validate:

- Geometry is not empty.
- Vertex positions contain finite values.
- Face indices are valid.
- At least one valid polygon exists.
- Bounding box dimensions are positive.
- Geometry does not contain invalid numerical values.

The mesh does not need to be watertight for the MVP.

Do not reject a valid visual reconstruction solely because the mesh is not suitable for 3D printing.

### 9.5. Mesh Processing

Only implement essential post-processing:

- Normal generation when required.
- Removal of invalid geometry.
- Basic bounding box calculation.
- Basic geometry validation.

Avoid unnecessary mesh decimation or aggressive smoothing.

The application must preserve the reconstructed geometry as closely as possible.

### 9.6. Coordinate System

Inspect the coordinate system and orientation of the generated mesh.

Ensure that the exported asset can be loaded and visualized consistently in Three.js.

The viewer may apply transformations for camera framing.

Do not silently modify physical proportions or distort the geometry.

---

## 10. Material and Texture Processing

### 10.1. General Requirements

The generated model must retain appearance information.

The MVP must support TripoSR's default vertex-color output.

### 10.2. Vertex Colors

The default export configuration must preserve vertex colors when available.

The GLB file must contain the necessary material settings so that Three.js can display the colors correctly.

### 10.3. Texture Baking

TripoSR supports optional texture baking.

The official implementation provides:

- `--bake-texture`
- `--texture-resolution`

Texture baking creates a texture atlas for the extracted mesh.

This functionality may be enabled through configuration after verifying the final output and its material references.

It is not mandatory for the initial MVP.

### 10.4. Texture Validation

When texture baking is enabled:

- Verify that texture files are generated.
- Verify that UV coordinates exist.
- Verify that materials reference the correct textures.
- Ensure that textures are embedded or correctly packaged in the exported GLB.

The primary browser-compatible result must be a self-contained GLB whenever practical.

### 10.5. Export Fallback

If texture baking fails but vertex-color export is available, the system may retry with the default vertex-color pipeline according to configuration.

Any fallback must be recorded in task metadata.

The application must not report a textured result when only vertex colors are available.

---

## 11. GLB Export

### 11.1. Primary Output Format

The primary MVP format is GLB.

Use the official TripoSR export capability or a compatible conversion step.

The official `run.py` implementation supports both OBJ and GLB mesh export.

### 11.2. Export Requirements

The generated asset must:

- Contain valid mesh geometry.
- Preserve available vertex colors or materials.
- Preserve supported textures.
- Use a format compatible with Three.js.
- Be stored as a self-contained GLB file where practical.

### 11.3. Output Naming

Use an internal unique filename.

Example:

```text
projects/{project_id}/results/{task_id}/model.glb
```

Never use the original uploaded filename as the generated model's storage filename.

### 11.4. Export Configuration

Initial recommended configuration:

```python
OBJECT_GENERATION_CONFIG = {
    "output_format": "glb",
    "chunk_size": 8192,
    "mc_resolution": 256,
    "remove_background": True,
    "foreground_ratio": 0.85,
    "bake_texture": False,
}
```

The configuration must be loaded through environment settings or a validated configuration module.

The values must not be scattered throughout the codebase.

### 11.5. Additional Export Formats

OBJ and STL are not mandatory for the first MVP release.

Future format conversion may be supported independently of TripoSR inference.

Do not advertise an export option before it is implemented and tested.

---

## 12. Output Validation

### 12.1. General Requirements

A task must not be marked COMPLETED merely because the inference function returned without raising an exception.

The generated file must pass validation.

### 12.2. Validation Pipeline

```text
Generated Mesh
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
Mesh Geometry Validation
     |
     v
Material and Color Validation
     |
     v
Bounding Box Validation
     |
     v
File Checksum
     |
     v
Validated Result
```

### 12.3. Required Checks

Verify:

1. Output file exists.
2. File size is greater than zero.
3. GLB container is valid.
4. glTF asset structure can be parsed.
5. At least one valid mesh exists.
6. Vertex coordinates are finite.
7. Face indices are valid.
8. Bounding box is valid.
9. Required appearance information is available.
10. The file checksum can be calculated.

### 12.4. Validation Failure

If any mandatory validation check fails:

- Do not create a successful GenerationResult.
- Mark the generation task as FAILED.
- Record an appropriate error code.
- Preserve diagnostic logs.
- Clean up invalid output files according to the retention policy.

### 12.5. Result Metadata

For successful results, record:

- Project ID.
- Task ID.
- File format.
- File size.
- SHA-256 checksum.
- Vertex count when available.
- Face count when available.
- Bounding box dimensions when available.
- Material and texture information when available.
- Generation configuration.

Metadata must be stored through the backend result persistence layer.

---

## 13. Celery Integration

### 13.1. Task Definition

Implement a dedicated Celery task for Object Generation.

Suggested name:

`generate_object_task`

The task must receive identifiers rather than image contents.

Example:

```python
generate_object_task.delay(
    project_id=str(project_id),
    task_id=str(task_id),
)
```

### 13.2. Task Execution Flow

The worker must:

1. Retrieve the generation task.
2. Verify that it is in PENDING state.
3. Verify that the project exists and is not deleted.
4. Retrieve the immutable input image reference.
5. Verify that the source image exists.
6. Update task and project statuses to PROCESSING.
7. Report IMAGE_PREPARATION.
8. Execute preprocessing.
9. Report MODEL_GENERATION.
10. Execute TripoSR inference.
11. Report MODEL_EXPORT.
12. Extract and export mesh.
13. Report RESULT_VALIDATION.
14. Validate the GLB file.
15. Store the final asset.
16. Create GenerationResult.
17. Update task status to COMPLETED.
18. Update project status to COMPLETED.

All related database updates must use appropriate transactions.

### 13.3. Progress Reporting

Use the following task stages:

```text
IMAGE_PREPARATION
MODEL_GENERATION
MODEL_EXPORT
RESULT_VALIDATION
```

The stages represent actual processing phases.

`COMPLETED` is a task status, not a processing stage. It must not be written to the `stage` field.

Do not create artificial progress percentages.

If a percentage is unavailable, persist it as NULL.

### 13.4. Task Idempotency

The worker must avoid producing duplicate or conflicting results after repeated task delivery.

Requirements:

- Check task status before processing.
- Claim the task through an atomic conditional transition from PENDING to PROCESSING.
- Do not start processing while another valid worker lease exists.
- Use a task-specific working directory.
- Store outputs in a task-specific location.
- Validate output before registering it.
- Avoid creating multiple GenerationResult records for one task.
- Use database constraints for result uniqueness.

### 13.5. Task Failure

On failure:

- Capture the exception.
- Record an error code.
- Save a user-friendly error message.
- Set the task status to FAILED.
- Set the project status to FAILED if the task is still the latest active attempt.
- Set the completion timestamp.
- Preserve diagnostic information.

A failure in one task must not terminate the entire worker process.

### 13.6. Retry Behavior

Support manual retry through a new generation task.

The previous failed task must remain in the database.

Automatic retry must be limited to transient infrastructure failures.

Examples:

- Temporary storage interruption.
- Temporary database connection interruption.
- Temporary worker communication failure.

Do not continuously retry:

- Invalid images.
- Deterministic preprocessing failures.
- Invalid model output.
- Repeated CUDA out-of-memory errors.

### 13.7. Worker Restart

After an unexpected worker restart:

- The worker must not leave tasks permanently in PROCESSING.
- Stale tasks must be detectable through heartbeat, lease expiration and task execution metadata.
- Recovery logic must determine whether to retry or fail an interrupted operation.
- A stale task must not be marked COMPLETED without validating the output asset.

---

## 14. Error Handling

### 14.1. Error Categories

Use stable error identifiers.

| Error Code | Description |
|---|---|
| SOURCE_IMAGE_NOT_FOUND | Source photograph is unavailable |
| IMAGE_DECODE_FAILED | Image cannot be decoded |
| INVALID_IMAGE_DIMENSIONS | Invalid image dimensions |
| BACKGROUND_REMOVAL_FAILED | Background removal failed |
| IMAGE_PREPROCESSING_FAILED | Preprocessing failed |
| MODEL_LOAD_FAILED | TripoSR could not be initialized |
| GPU_UNAVAILABLE | Required GPU is unavailable |
| GPU_OUT_OF_MEMORY | GPU memory exhausted |
| CUDA_EXECUTION_FAILED | CUDA execution error |
| MODEL_INFERENCE_FAILED | Inference failed |
| MODEL_TIMEOUT | Processing exceeded the configured timeout |
| MESH_EXTRACTION_FAILED | Mesh extraction failed |
| INVALID_MESH | Mesh validation failed |
| GLB_EXPORT_FAILED | GLB export failed |
| GLB_VALIDATION_FAILED | Exported GLB is invalid |
| STORAGE_WRITE_FAILED | Generated asset could not be stored |
| RESULT_PERSISTENCE_FAILED | Result metadata could not be persisted |

### 14.2. Error Information

Store:

- Error code.
- User-friendly message.
- Task identifier.
- Processing stage.
- Failure timestamp.

Full exception details and stack traces must remain in worker logs.

Do not expose internal file paths, model implementation details or raw CUDA exceptions to users.

### 14.3. Previous Result Preservation

If a new generation task fails:

- Do not delete previous successful results.
- Do not change the current result reference.
- Keep the previous GLB available for download.
- Record the failed generation attempt.

---

## 15. Performance and Optimization

### 15.1. Model Initialization

Keep the model loaded within the worker process.

Avoid repeated model downloads and repeated model initialization.

### 15.2. GPU Utilization

Use a configurable worker concurrency.

For the MVP, use one active generation task per GPU.

Multiple worker processes must not accidentally load duplicate model instances onto the same GPU without explicit resource planning.

### 15.3. Image Processing

Avoid unnecessary image resizing and format conversion.

Use a controlled preprocessing pipeline.

Preserve the original image.

### 15.4. Output Optimization

Do not perform aggressive polygon reduction as a mandatory part of MVP generation.

Record output mesh statistics.

Any future optimization must be evaluated for visual quality and compatibility.

### 15.5. Processing Metrics

Record:

- Worker initialization and model loading duration.
- Image preprocessing duration.
- Model inference duration.
- Mesh extraction duration.
- Export duration.
- Total task duration.
- Peak GPU memory when available.

Worker initialization and model loading time must be measured separately from individual inference execution time.

GPU memory measurements must distinguish model initialization from task-specific peak memory consumption.

These metrics are intended for diagnostics and performance evaluation.

Do not use them to fabricate user-facing progress.

---

## 16. Configuration

All processing parameters must be configurable.

Example environment configuration:

```env
OBJECT_GENERATION_ENABLED=true

OBJECT_MODEL_ID=stabilityai/TripoSR
OBJECT_MODEL_REVISION=<PINNED_MODEL_REVISION>

OBJECT_DEVICE=cuda:0
OBJECT_ALLOW_CPU_FALLBACK=false

OBJECT_CHUNK_SIZE=8192
OBJECT_MC_RESOLUTION=256

OBJECT_REMOVE_BACKGROUND=true
OBJECT_FOREGROUND_RATIO=0.85

OBJECT_OUTPUT_FORMAT=glb
OBJECT_BAKE_TEXTURE=false
OBJECT_TEXTURE_RESOLUTION=2048

OBJECT_MAX_TASK_TIME_SECONDS=600
OBJECT_WORKER_CONCURRENCY=1
```

Important:

- `OBJECT_MODEL_REVISION` must contain a concrete, verified commit or model revision at implementation time.
- `main` must never be used as a production dependency. Changes in the external repository must not silently change the build or generation behavior.
- The TripoSR repository revision and pretrained model revision must be explicitly pinned and recorded.
- The worker must verify model availability and compatibility before accepting processing tasks.
- The model weights must be verified before use.
- Hardware-specific parameters must be validated against the deployment GPU.
- Texture settings must only be used when texture baking is enabled.

Do not hardcode these values in inference logic.

---

## 17. Testing Requirements

### 17.1. Unit Tests

Test individual processing components.

Required tests:

- Image decoding.
- EXIF orientation handling.
- Input normalization.
- Background removal.
- Foreground resizing.
- Mesh validation.
- GLB validation.
- Output checksum calculation.
- Error mapping.

### 17.2. Integration Tests

Test:

- TripoSR model initialization.
- Model inference using a sample photograph.
- Mesh extraction.
- GLB export.
- Result storage.
- GenerationResult persistence.
- Task status updates.

### 17.3. Test Images

Prepare a small test dataset containing different object categories.

Examples:

- Chair.
- Table.
- Lamp.
- Shoe.
- Backpack.
- Bottle.
- Toy.
- Household appliance.

Include images with:

- Plain backgrounds.
- Complex backgrounds.
- Different lighting.
- Different object scales.
- Partial occlusion.

Do not use only one test photograph to evaluate the implementation.

### 17.4. GPU Tests

Verify:

- CUDA detection.
- Model loading.
- Successful inference.
- GPU memory usage.
- GPU out-of-memory handling.
- Worker behavior after failure.
- Subsequent task execution after a failed task.

### 17.5. Output Tests

Verify:

- Valid GLB generation.
- Geometry visibility.
- Material and color preservation.
- Loading through Three.js.
- Browser camera interaction.
- File download.

### 17.6. Performance Tests

Measure:

- Model initialization time.
- Preprocessing time.
- Inference time.
- Mesh extraction time.
- Export time.
- Total end-to-end processing time.
- Peak VRAM consumption.

The A100 performance reported in the original TripoSR research must not be treated as a performance guarantee for other GPUs.

### 17.7. Real Inference Requirement

At least one integration test must execute the actual TripoSR model with real pretrained weights.

Mocked model inference may be used in ordinary backend tests but must not replace the actual integration test.

---

## 18. Acceptance Criteria

### OBJ-AC-01. Worker Initialization

The Object Worker starts successfully and initializes the configured TripoSR model.

### OBJ-AC-02. Model Availability

The worker verifies that the required pretrained weights are available before accepting generation tasks.

### OBJ-AC-03. GPU Detection

The worker detects the configured CUDA device and reports unavailable hardware correctly.

### OBJ-AC-04. Input Validation

Only valid JPEG and PNG photographs can enter the preprocessing pipeline.

### OBJ-AC-05. Original Image Preservation

The original uploaded photograph remains unchanged after preprocessing.

### OBJ-AC-06. Background Removal

The preprocessing pipeline performs background removal and foreground preparation according to configuration.

### OBJ-AC-07. Single-Image Generation

A valid source photograph can be processed using TripoSR to produce actual mesh geometry.

### OBJ-AC-08. Mesh Extraction

The reconstructed mesh passes geometry validation.

### OBJ-AC-09. GLB Export

The worker exports a valid GLB asset compatible with Three.js.

### OBJ-AC-10. Appearance Preservation

Available vertex colors or supported materials are preserved in the exported asset.

### OBJ-AC-11. Result Persistence

The generated model is stored in persistent storage and registered in PostgreSQL.

### OBJ-AC-12. Task Status

The task status correctly transitions through PENDING, PROCESSING and COMPLETED.

### OBJ-AC-13. Error Handling

Inference, preprocessing, export and GPU errors are correctly recorded.

### OBJ-AC-14. GPU Memory Management

The worker can process subsequent tasks after a failed generation without becoming permanently unusable.

### OBJ-AC-15. Result Preservation

Failed regeneration does not remove previously generated successful assets.

### OBJ-AC-16. Asynchronous Processing

Generation runs outside the FastAPI request-handling process.

### OBJ-AC-17. Real Model Execution

The system successfully generates a 3D model using the actual TripoSR pretrained model.

### OBJ-AC-18. Docker Integration

The Object Worker can run as an independent service within the Docker Compose environment with the required GPU access.

---

## 19. Implementation Order

### Phase 1. TripoSR Environment

- Clone the official repository.
- Pin the repository revision.
- Configure Python environment.
- Install PyTorch.
- Configure CUDA.
- Download pretrained weights.
- Verify model initialization.

### Phase 2. Standalone Inference

- Prepare a test photograph.
- Execute TripoSR inference.
- Extract mesh geometry.
- Export a GLB model.
- Open the result in a 3D viewer.
- Verify geometry and appearance.

### Phase 3. Processing Pipeline

- Implement image decoding.
- Implement background removal.
- Implement foreground preparation.
- Implement inference adapter.
- Implement mesh validation.
- Implement GLB exporter.
- Implement error handling.

### Phase 4. Worker Integration

- Configure Celery worker.
- Implement object-generation task.
- Add task status updates.
- Add input snapshot retrieval.
- Add isolated working directories.
- Add GPU resource management.

### Phase 5. Backend Integration

- Integrate with GenerationService.
- Connect task creation.
- Implement result registration.
- Implement result persistence.
- Implement failure reporting.
- Implement retry behavior.

### Phase 6. Testing and Stabilization

- Complete unit tests.
- Execute real TripoSR inference tests.
- Test GPU memory limitations.
- Test worker restart behavior.
- Test GLB downloads.
- Test Three.js compatibility.
- Verify Docker Compose execution.

---

## 20. Related Specifications

This document defines the Object Generation processing pipeline.

Related documents:

- `00_project_overview.md` — overall project architecture.
- `01_product_requirements.md` — object generation requirements.
- `03_frontend_specification.md` — frontend interaction and viewer.
- `04_backend_specification.md` — backend and worker integration.
- `05_database_specification.md` — task and result persistence.
- `07_scene_reconstruction.md` — scene reconstruction pipeline.
- `08_infrastructure.md` — ML worker deployment and GPU configuration.
- `09_testing.md` — system testing.
- `10_development_roadmap.md` — implementation sequence.
- `AI_DEVELOPMENT_GUIDE.md` — development workflow, quality gates and agent rules.

The implementation must use the official TripoSR codebase and pretrained model weights, subject to the pinned versions and applicable license terms.