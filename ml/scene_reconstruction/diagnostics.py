"""Reconstruction diagnostics and result metadata (07 Section 12).

The metrics are persisted as optional result metadata and written to
``diagnostics.json`` in the task workspace. They are internal evidence: tool
logs, absolute paths and command lines never reach the API (07 Section 17.4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .colmap_runner import DatabaseStats
from .mesh_processor import MeshStats
from .reconstruction_selector import ModelCandidate, ReconstructionSelection
from .validator import SceneGLBValidation


@dataclass(slots=True)
class ReconstructionDiagnostics:
    """Everything measured while reconstructing one scene."""

    input_images: int = 0
    unique_images: int = 0
    image_formats: dict[str, int] = field(default_factory=dict)
    image_dimensions: tuple[tuple[int, int], ...] = ()
    duplicate_images: tuple[str, ...] = ()
    tool_versions: dict[str, str] = field(default_factory=dict)
    database: DatabaseStats | None = None
    candidates: tuple[ModelCandidate, ...] = ()
    selection_reason: str = ""
    dense_points: int | None = None
    mesh: MeshStats | None = None
    refined_mesh: MeshStats | None = None
    texture_count: int = 0
    glb: SceneGLBValidation | None = None
    raw_export: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    stage_timings: dict[str, float] = field(default_factory=dict)
    total_seconds: float = 0.0

    def record_selection(self, selection: ReconstructionSelection) -> None:
        self.candidates = selection.candidates
        self.selection_reason = selection.reason
        self.warnings.extend(selection.warnings)

    def record_stage(self, stage: str, duration_seconds: float) -> None:
        self.stage_timings[stage] = round(float(duration_seconds), 3)

    def as_metadata(self) -> dict[str, Any]:
        """Return the JSONB-safe result metadata (07 Section 12.2)."""
        metadata: dict[str, Any] = {
            "input_images": self.input_images,
            "unique_images": self.unique_images,
            "image_formats": dict(self.image_formats),
            "image_dimensions": [list(pair) for pair in self.image_dimensions],
            "duplicate_images": list(self.duplicate_images),
            "tool_versions": dict(self.tool_versions),
            "sparse_reconstruction": {
                "selected_model": self.candidates[0].model_dir.name if self.candidates else None,
                "selection_reason": self.selection_reason,
                "candidates": [candidate.as_metadata() for candidate in self.candidates],
                "database": {
                    "images": self.database.images,
                    "keypoints": self.database.keypoints,
                    "matched_pairs": self.database.matched_pairs,
                    "verified_pairs": self.database.verified_pairs,
                    "components": self.database.components,
                }
                if self.database
                else None,
            },
            "dense_points": self.dense_points,
            "mesh": self.mesh.as_metadata() if self.mesh else None,
            "refined_mesh": self.refined_mesh.as_metadata() if self.refined_mesh else None,
            "texture_count": self.texture_count,
            "raw_export": dict(self.raw_export),
            "glb_validation": self.glb.as_metadata() if self.glb else None,
            "warnings": sorted(set(self.warnings)),
            "stage_seconds": dict(self.stage_timings),
            "total_seconds": round(self.total_seconds, 3),
        }
        return metadata

    def write(self, path: Path) -> None:
        """Persist the same document for offline inspection."""
        targets = Path(path)
        targets.parent.mkdir(parents=True, exist_ok=True)
        targets.write_text(
            json.dumps(
                {
                    "metadata": self.as_metadata(),
                    "candidates": [candidate.as_metadata() for candidate in self.candidates],
                },
                indent=2,
                sort_keys=True,
                default=str,
            ),
            encoding="utf-8",
        )


__all__ = ["ReconstructionDiagnostics"]
