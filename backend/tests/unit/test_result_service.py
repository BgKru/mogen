"""Result download helpers: key naming, safe filenames and stream closure."""

from __future__ import annotations

import io
import uuid

import pytest

from app.services.result_service import (
    STREAM_CHUNK_SIZE,
    ascii_download_name,
    content_disposition,
    result_storage_key,
    stream_result,
)


def test_result_storage_key_is_server_generated_and_task_scoped() -> None:
    project_id = uuid.uuid4()
    task_id = uuid.uuid4()

    key = result_storage_key(project_id, task_id)

    assert key == f"projects/{project_id}/results/{task_id}/model.glb"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Chair", "Chair"),
        ("My object 42", "My_object_42"),
        ("Модель кресла", "model"),
        ("../../etc/passwd", "etc_passwd"),
        ("a/b\\c:d*e", "a_b_c_d_e"),
        ("   ", "model"),
        ("x" * 200, "x" * 80),
    ],
)
def test_ascii_download_name_is_safe(name: str, expected: str) -> None:
    assert ascii_download_name(name) == expected


def test_content_disposition_has_ascii_and_unicode_forms() -> None:
    header = content_disposition("Кресло 42")

    assert header.startswith('attachment; filename="')
    assert 'filename="42.glb"' in header
    assert "filename*=UTF-8''%D0%9A%D1%80%D0%B5%D1%81%D0%BB%D0%BE%2042.glb" in header
    assert "\r" not in header and "\n" not in header


def test_content_disposition_cannot_inject_a_header() -> None:
    header = content_disposition('x"; filename="evil\r\nX-Injected: yes')

    assert "\r" not in header and "\n" not in header
    assert header.startswith("attachment;")
    # The quote from the project name is percent-encoded, never emitted raw.
    assert '"evil' not in header


def test_stream_result_closes_the_handle_even_when_the_reader_stops() -> None:
    class TrackedStream(io.BytesIO):
        closed_by_us = False

        def close(self) -> None:
            self.closed_by_us = True
            super().close()

    payload = b"a" * (STREAM_CHUNK_SIZE + 10)
    stream = TrackedStream(payload)
    chunks = stream_result(stream)

    assert next(chunks) == payload[:STREAM_CHUNK_SIZE]
    chunks.close()  # type: ignore[attr-defined]
    assert stream.closed_by_us is True
