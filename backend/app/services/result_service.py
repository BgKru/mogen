"""Result retrieval and download (04_backend_specification.md Section 13,
api_contracts.md Section 10).

Only the *current*, successfully validated generation result is exposed. A
failed regeneration never changes the current result, so the previous GLB stays
downloadable (06_object_generation.md Section 14.3; OBJ-AC-15).
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import BinaryIO
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.db.models import GenerationResult, Project
from app.repositories import ProjectRepository, ResultRepository
from app.storage import StorageBackend

logger = logging.getLogger(__name__)

RESULT_NOT_FOUND = "RESULT_NOT_FOUND"
RESULT_FILE_MISSING = "RESULT_FILE_MISSING"
PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
STREAM_CHUNK_SIZE = 64 * 1024
_DOWNLOAD_NAME_MAX = 80
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


def result_storage_key(
    project_id: uuid.UUID, task_id: uuid.UUID, *, filename: str = "model.glb"
) -> str:
    """Return the internal storage key for a task's generated GLB.

    The name is server-generated and never derived from the uploaded filename
    (06_object_generation.md Section 11.3). Object results use ``model.glb``;
    scene reconstructions use ``scene.glb`` (07 Section 11.4).
    """
    return f"projects/{project_id}/results/{task_id}/{filename}"


def ascii_download_name(project_name: str) -> str:
    """Return a conservative ASCII base name for Content-Disposition."""
    normalized = unicodedata.normalize("NFKD", project_name)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = _UNSAFE_FILENAME.sub("_", ascii_text).strip(" ._")
    cleaned = re.sub(r"[\s_]+", "_", cleaned)
    if not cleaned:
        cleaned = "model"
    return cleaned[:_DOWNLOAD_NAME_MAX]


def content_disposition(project_name: str) -> str:
    """Build a safe ``attachment`` header with an RFC 5987 Unicode name.

    The ASCII fallback is always present for legacy clients; the UTF-8 variant
    preserves the user's project name without allowing header injection.
    """
    full_name = f"{project_name.strip() or 'model'}.glb"
    fallback = f"{ascii_download_name(project_name)}.glb"
    encoded = quote(full_name, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


@dataclass(frozen=True, slots=True)
class ResultDownload:
    """A current result and an open binary stream to its GLB."""

    result: GenerationResult
    project: Project
    stream: BinaryIO


class ResultService:
    """Read the current result and stream its asset with ownership checks."""

    def __init__(self, session: Session, storage: StorageBackend) -> None:
        self._db = session
        self._storage = storage
        self._projects = ProjectRepository(session)
        self._results = ResultRepository(session)

    def _owned_project(self, project_id: uuid.UUID, user_id: uuid.UUID) -> Project:
        project = self._projects.get_active_for_user(project_id, user_id)
        if project is None:
            raise AppError(404, PROJECT_NOT_FOUND, "Project not found.")
        return project

    def get_current(self, *, user_id: uuid.UUID, project_id: uuid.UUID) -> GenerationResult:
        """Return the current result metadata for an owned project."""
        project = self._owned_project(project_id, user_id)
        result = self._results.get_current_for_project(project.id)
        if result is None:
            raise AppError(404, RESULT_NOT_FOUND, "The project has no generated result.")
        return result

    def open_download(self, *, user_id: uuid.UUID, project_id: uuid.UUID) -> ResultDownload:
        """Open the current result's stored GLB, mapping a missing file to 404."""
        project = self._owned_project(project_id, user_id)
        result = self._results.get_current_for_project(project.id)
        if result is None:
            raise AppError(404, RESULT_NOT_FOUND, "The project has no generated result.")
        try:
            stream = self._storage.open(result.storage_key)
        except FileNotFoundError as exc:
            logger.error(
                "result_content_missing",
                extra={
                    "operation": "result_download",
                    "project_id": str(project.id),
                    "result_id": str(result.id),
                },
            )
            raise AppError(
                404, RESULT_FILE_MISSING, "The generated asset is no longer available."
            ) from exc
        return ResultDownload(result=result, project=project, stream=stream)


def stream_result(stream: BinaryIO):
    """Yield a GLB in bounded chunks and always close the handle."""
    try:
        while chunk := stream.read(STREAM_CHUNK_SIZE):
            yield chunk
    finally:
        stream.close()
