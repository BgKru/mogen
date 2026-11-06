# Phase 0 Decisions and M0 Evidence

## 1. Purpose

This document records the outcome of Phase 0 of `10_development_roadmap.md` and the evidence for milestone M0 — Architecture Ready.

It contains:

- The audit result for Phase 0 tasks 0.1–0.8.
- The evaluation of the six M0 acceptance criteria.
- The conflicts that were found and how they were resolved.
- The pinned dependency and licensing decisions.
- The development hardware profile.
- The verification that is explicitly deferred, with its acceptance gate.

Nothing here overrides the subsystem specifications. Where a decision changes a specification, the specification itself was updated and is named in Section 5.

---

## 2. Milestone Status

| Item | Status |
|---|---|
| Phase 0 tasks 0.1–0.7 | Complete |
| Phase 0 task 0.8 | Complete except one deferred empirical verification (`P0-FU-1`, Section 10) |
| M0 acceptance criteria | All six satisfied |
| M0 | Satisfied, with `P0-FU-1` tracked as an open verification that must close before Phase 6 |

M0 is an architecture milestone. `P0-FU-1` is an execution check that requires a built worker image, so it belongs to the build phase while its decision belongs to Phase 0. The decision is made below; the check is scheduled.

---

## 3. Task Audit

| Task | Verdict | Evidence |
|---|---|---|
| 0.1 Review specifications, identify conflicts | Done | Specification set reviewed (11 specifications, 3 architecture documents); 8 conflicts found and resolved (Section 5) |
| 0.2 Architecture documents | Done | `system_architecture.md` (components, boundaries, decisions), `api_contracts.md` (canonical request/response schemas), `data_flow.md` (upload, dispatch, execution, persistence, download, deletion) |
| 0.3 `outbox_messages` table | Done | `05_database_specification.md` Section 13: columns, statuses, indexes, dispatcher requirements, payload rules, plus event-type enumeration (13.7) and retry policy (13.6) added in Phase 0 |
| 0.4 Task lifecycle | Done | Project statuses and task statuses enumerated identically in `05_database_specification.md` (7.3, 9.3), `04_backend_specification.md` (11.3), `api_contracts.md` (5.3, 5.4) and `system_architecture.md` (13.1, 13.2); stage identifiers agree across 05, 04, 06, 07 and `data_flow.md` |
| 0.5 API contracts | Done | `api_contracts.md`: auth payloads, cookie and CSRF rules, project creation, upload, generation, status, result metadata, download, error format and codes, pagination |
| 0.6 Third-party dependencies | Done | Section 6 records pins, compatibility strategy and licenses; Section 11 records what remains unverified |
| 0.7 Development hardware profile | Done | Section 9 |
| 0.8 Cross-cutting contracts | Partly complete | CSRF double-submit, session binding and rotation, worker lease and recovery, cancellation, deletion coordination, composite ownership, request fingerprint: defined. OpenMVS GLB export verified only on paper: `P0-FU-1` |

---

## 4. Acceptance Criteria Evaluation

| Criterion | Verdict | Basis |
|---|---|---|
| All subsystem specifications use consistent terminology | Met | Status, task-type and stage enumerations compared word for word across six documents; one frontend type error found and fixed |
| API contracts are defined | Met | `api_contracts.md` covers every endpoint in `04_backend_specification.md` |
| Database entities support all required workflows | Met | Entities cover upload, generation, result versioning, cleanup and outbox dispatch |
| Outbox functionality is reflected in the database model | Met | Table, statuses, indexes, event types and retry policy are defined |
| ML dependencies have a documented compatibility strategy | Met | Sections 6 and 7 |
| No critical architectural conflicts remain unresolved | Met | Section 5; the OpenMVS export path is decided, and its empirical check is scheduled |

---

## 5. Conflicts Resolved

| Conflict | Resolution |
|---|---|
| `AI_DEVELOPMENT_GUIDE.md` listed object generation before asynchronous processing, contradicting its own outbox and worker rules | Priority list reordered; ordering delegated to the roadmap |
| Repository contained a Java/Maven archetype scaffold contradicting the approved Python/React stack | Scaffold deleted; rule added to the guide (Section 5.4) so the case is handled explicitly in future |
| `.gitignore` was a Java/IDE template with no secret or artifact exclusions | Replaced with Python/React/ML/storage exclusions |
| Outbox `event_type` had one example value and no enumeration; `data_flow.md` routed by event type but tabulated task type | Event types and payload contracts enumerated (`05_database_specification.md` 13.7); routing table corrected in `data_flow.md` 7.1 |
| Outbox retry policy was referenced but never defined, and the status enum had no terminal state | Retry policy, backoff, attempt limit, exhaustion behavior and `FAILED` status defined (`05_database_specification.md` 13.6) |
| Frontend typed a generation task's `status` as `ProjectStatus`, which omits `CANCELLED` | `TaskStatus` type added; task interface corrected (`03_frontend_specification.md` 7.5) |
| Scene reconstruction assumed a single-file GLB from OpenMVS, which exports the texture as a sidecar | Repack stage, embedded-asset assertions and unlit-material caveat specified (`07_scene_reconstruction.md` 11.2) |
| CSRF rotation was mentioned without triggers, invalidation or lifetime | Rotation triggers, invalidation rule and session-bound lifetime defined (`04_backend_specification.md` 8.5) |

Not changed, after verification: project and task status enumerations in `01_product_requirements.md`, `02_ui_ux_specification.md`, `04_backend_specification.md`, `05_database_specification.md`, `api_contracts.md` and `system_architecture.md` already agreed.

---

## 6. Pinned Dependency Decisions

These are initial decisions for implementation. Each pin must be replaced by a digest or exact version in the Phase 1 build files, and the replacement recorded here.

| Component | Pin | License | Rationale |
|---|---|---|---|
| Python (backend and workers) | 3.11.x | PSF | Inside the worker image. Satisfies torch 2.14.1 (`>=3.10`) and is the lowest floor that survives a later move to torch 2.15, which drops cp310 |
| PyTorch build image | `pytorch/pytorch:2.14.1-cuda12.6-cudnn9-devel` | BSD-3-Clause | Build stage only. `devel` is required to compile `torchmcubes` with nvcc |
| PyTorch runtime image | `pytorch/pytorch:2.14.1-cuda12.6-cudnn9-runtime` | BSD-3-Clause | Production worker stage; artifacts are copied from the build stage |
| PyTorch and CUDA | torch 2.14.1, CUDA 12.6, cuDNN 9 | BSD-3-Clause | CUDA 12.6 is the common denominator for compiling `torchmcubes` and building COLMAP and OpenMVS with CUDA. PyTorch 2.15 requires CUDA 13, a driver of 580 or newer and Turing or newer GPUs, which excludes older or mixed hardware |
| TripoSR | commit `d26e33181947bbbc4c6fc0f5734e1ec6c080956e` | MIT | The repository has no tags or releases; the last functional commit dates to 2024-05-14. Pinning by branch is not reproducible |
| torchmcubes | `tatsy/torchmcubes` at a pinned commit, built as a wheel | MPL-2.0 | Mandatory TripoSR dependency. It is a compiled CUDA extension and must be built against the exact torch and CUDA versions. Its license is not MIT |
| COLMAP | 4.2.1, image `colmap/colmap:20260929.8466` | BSD-3-Clause | Official image ships CUDA support; distribution packages do not |
| OpenMVS | v2.4.0, built from source | AGPL-3.0 | No current official image exists; the Docker Hub image dates to 2019 and vcpkg lags at 2.3.0 |
| trimesh | 4.x, pinned in Phase 1 | MIT | GLB repack after OpenMVS export |
| glTF Validator | 2.0.0-dev.3.10 | Apache-2.0 | Asset validation in the pipeline and in CI |
| PostgreSQL | 17.11, `postgres@sha256:748a18a5…` | PostgreSQL License | Replaces the illustrative tag in the infrastructure specification. Version and digest verified in Phase 1 |
| Redis | 7.4.12, `redis@sha256:8da19c73…` | RSALv2 / SSPLv1 | Version and digest verified in Phase 1. See the licensing note in Section 8 before commercial deployment |
| Node.js (frontend) | 24.22.2, `node:24-alpine@sha256:8a32c8cf…` | MIT | LTS line. Version and digest verified in Phase 1; the frontend image pins the digest |

TripoSR's own `requirements.txt` is not a reproducible lockfile: `torch` is unpinned, `torchmcubes` is a git URL without a commit, and `rembg`, `gradio`, `huggingface-hub` and `imageio` are unpinned. The project must vendor a lockfile, as required by `06_object_generation.md`, Section 4.

---

## 7. Compatibility Strategy

1. Compile in a `-devel` image, copy wheels and binaries into a `-runtime` image. Never ship nvcc.
2. Build `torchmcubes` once in CI against the pinned torch and CUDA, publish the wheel, and install the wheel at build time. Do not run `pip install git+...` during deployment.
3. Maintain a lockfile for backend and worker dependencies. Phase 1 must be able to rebuild the environment byte for byte.
4. Keep COLMAP and OpenMVS as separate images and separate processes. Their CUDA requirements and licenses differ from TripoSR's.
5. Pin everything by digest where an image is used, and by exact version or commit where a package is installed.
6. Prove the stack with a smoke test on the first build: import torch, report CUDA availability, import `torchmcubes`, load TripoSR weights, generate one GLB from the sample image.
7. Test CPU-only operation explicitly. `OBJECT_ALLOW_CPU_FALLBACK` exists for this purpose, and no deployment may assume a GPU.

Version facts to verify in Phase 1, not to assume:

- The Python version inside the pinned PyTorch image. Confirm with `python -V`; do not infer it from the tag.
- That TripoSR runs unmodified on torch 2.14. It predates that release by more than two years and has no upstream test matrix.
- The minimum NVIDIA driver for the CUDA 12.6 line.

---

## 8. Licensing Decisions

| Component | License | Decision |
|---|---|---|
| TripoSR | MIT | Acceptable. Retain the notice |
| PyTorch | BSD-3-Clause | Acceptable. Retain the notice |
| COLMAP | BSD-3-Clause | Acceptable. COLMAP's own notice warns that optional dependencies can affect the resulting license, so the build recipe must be recorded |
| trimesh, glTF Validator | MIT, Apache-2.0 | Acceptable. Retain the notices |
| torchmcubes | MPL-2.0 | Acceptable while unmodified and dynamically linked. File-level copyleft: modifications to its files must be published. Ship the wheel unmodified |
| OpenMVS | AGPL-3.0-only | Accepted with constraints. Invoke unmodified OpenMVS executables as separate processes; do not link its libraries into application code; do not modify it. If a container containing OpenMVS is distributed, the corresponding source must be offered. Section 13 of the license is the network-use trigger for modified versions |
| Redis | RSALv2 / SSPLv1 | Open question. These are not OSI-approved licenses. Before commercial deployment, either accept the terms under legal review or request approval to change the approved broker, for example to a BSD-licensed alternative. The stack table lists Redis, so any change needs explicit approval |

This section records engineering decisions, not legal advice. The OpenMVS review required by `07_scene_reconstruction.md`, Section 23, is satisfied by this decision; a formal legal review remains necessary before public deployment.

OpenMVS's transitive dependencies (CGAL, Boost, OpenCV, Eigen, VCGLib) were not individually audited.

---

## 9. Development Hardware Profile

### 9.1. Reference Development Machine

Measured on the machine used for Phase 0.

| Property | Value |
|---|---|
| Operating system | Windows 11, build 10.0.26200 |
| CPU | AMD Ryzen 7 5700X, 8 cores / 16 threads |
| RAM | 31.9 GB |
| GPU | NVIDIA GeForce RTX 3060 |
| VRAM | 12 GB |
| GPU driver | 617.42 |
| Workspace disk (H:) | 931.5 GB total, 305.3 GB free, NTFS |
| System disk (C:) | 220.7 GB total, 11.8 GB free, NTFS |
| Docker | 28.1.1 |
| Python (host) | 3.14.6 |
| Node.js (host) | 26.13.0 |
| Git | 2.45.1 |

Two consequences follow from this profile:

- The host Python version is irrelevant to the application, which runs in containers. It must not be used to create the backend virtual environment; that environment must use the pinned 3.11.
- The system disk has 11.8 GB free. Docker image layers for PyTorch build images and for a source-built OpenMVS exceed that. The Docker data root must be relocated to the workspace disk before Phase 1 builds.

### 9.2. Minimum Requirements

Derived requirements for another development machine. They are engineering estimates to be validated during Phase 1.

| Property | Minimum | Recommended | Basis |
|---|---|---|---|
| CPU | 4 cores | 8 cores | COLMAP feature extraction and matching dominate scene reconstruction runtime |
| RAM | 16 GB | 32 GB | Dense reconstruction and container overhead |
| GPU | NVIDIA, 6 GB VRAM | NVIDIA, 12 GB VRAM | TripoSR default inference uses about 6 GB; dense reconstruction benefits from headroom |
| Disk | 50 GB free | 100 GB free | Images, COLMAP intermediate data, GLB artifacts and model weights |
| OS | Windows 10/11 with WSL2, or Linux | Linux | Docker Desktop on Windows requires WSL2 for acceptable bind-mount performance |
| Docker | Engine 24 or newer, Compose v2 | Current release | Required for health checks and Compose features used by the specification |

The application must still start and serve object generation on CPU-only hardware, with the explicit error behavior required by `06_object_generation.md`. GPU absence is a supported degraded mode, not an unsupported one.

---

## 10. Deferred Verification: `P0-FU-1`

**Subject:** single-file GLB export from the pinned OpenMVS build.

**Why it is deferred:** the check requires a built worker image containing OpenMVS 2.4.0 and its CUDA dependencies. It cannot be performed from documentation, and Phase 0 produced no images.

**Why it is not a documentation risk:** the architectural decision is made. OpenMVS writes glTF 2.0 with embedded buffers but a sidecar texture, and marks materials `KHR_materials_unlit`. The pipeline therefore requires the repack stage now specified in `07_scene_reconstruction.md`, Section 11.2.

**Procedure, to be executed in the worker image:**

1. Build or pull the pinned OpenMVS 2.4.0 image.
2. Run the exporter on a small textured scene and record the exact command and output filenames.
3. Confirm whether the texture is a sidecar file and whether `images[].uri` is present.
4. Repack to a single-file GLB with the pinned trimesh version.
5. Validate with the glTF Validator and record the report.
6. Assert that the result has no `images[].uri`, exactly one embedded buffer, and at least one primitive with `TEXCOORD_0`.
7. Load the result in Three.js and record whether the unlit material is acceptable or must be converted.

**Gate:** this check must pass before Phase 6 can be reported complete. If the repack proves unreliable, a fallback asset strategy requires approval under `AI_DEVELOPMENT_GUIDE.md`, Section 4.5.

---

## 11. Risks Carried into Phase 1

1. **TripoSR is unmaintained.** No tags, no releases, last functional commit in 2024, and a large open issue backlog. There will be no upstream fixes. The commit pin and a smoke test are the only protection.
2. **The TripoSR dependency set is not reproducible as published.** A project lockfile and a prebuilt `torchmcubes` wheel are prerequisites, not improvements.
3. **`torchmcubes` is the most common build failure.** It must be compiled against the exact torch and CUDA pair, in the build stage, once.
4. **Host tooling is newer than the pinned stack.** Python 3.14.6 and Node 26.13.0 exist on the reference machine; the application pins 3.11 inside the image. Developers must not build the backend with the host interpreter.
5. **Disk pressure on the system drive.** See Section 9.1.
6. **OpenMVS licensing.** Acceptable only while the constraints in Section 8 hold. Any modification, or linking its libraries, changes the analysis.
7. **Redis license.** Unresolved; see Section 8.
8. **GPU coverage.** The reference machine has one 12 GB GPU. Multi-GPU behavior, pre-Turing GPUs and CUDA 13 paths are untested and out of MVP scope.

---

## 12. Sources

Dependency facts in Sections 6–8 were verified against the following primary sources at the time of Phase 0:

- TripoSR repository, commits, tags and license: `https://github.com/VAST-AI-Research/TripoSR`, `https://api.github.com/repos/VAST-AI-Research/TripoSR/tags`
- PyTorch 2.15 release notes: `https://github.com/pytorch/pytorch/releases/tag/v2.15.0`
- PyTorch image tags: `https://hub.docker.com/v2/repositories/pytorch/pytorch/tags`
- torch 2.14.1 metadata: `https://pypi.org/pypi/torch/2.14.1/json`
- COLMAP release, license and installation: `https://github.com/colmap/colmap/releases/tag/4.2.1`, `https://colmap.github.io/install.html`
- OpenMVS release and license: `https://github.com/cdcseacave/openMVS/releases/tag/v2.4.0`, `https://github.com/cdcseacave/openMVS/blob/master/LICENSE`
- OpenMVS GLB export behavior: `https://github.com/cdcseacave/openMVS/blob/master/libs/MVS/Mesh.cpp`, `https://github.com/cdcseacave/openMVS/issues/1013`
- glTF Validator: `https://www.npmjs.com/package/gltf-validator`
- Three.js GLTFLoader: `https://github.com/mrdoob/three.js/blob/dev/examples/jsm/loaders/GLTFLoader.js`

These are external sources. They were read as evidence, and any change to them invalidates the corresponding decision.
