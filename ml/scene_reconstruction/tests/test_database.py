"""COLMAP database statistics, including pair-id decoding (07 Section 7.6)."""

from __future__ import annotations

import sqlite3

from scene_reconstruction.colmap_runner import (
    COLMAP_MAX_IMAGES,
    _pair_image_ids,
    read_database_stats,
)


def test_pair_ids_decode_to_the_two_image_ids():
    assert _pair_image_ids(1 * COLMAP_MAX_IMAGES + 2) == (1, 2)
    assert _pair_image_ids(7 * COLMAP_MAX_IMAGES + 11) == (7, 11)


def test_reads_current_colmap_schema_without_image_id_columns(tmp_path):
    path = tmp_path / "database.db"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE images (image_id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE keypoints (image_id INTEGER, rows INTEGER);
            CREATE TABLE matches (pair_id INTEGER, rows INTEGER);
            CREATE TABLE two_view_geometries (
                pair_id INTEGER PRIMARY KEY,
                rows INTEGER,
                cols INTEGER,
                config INTEGER
            );
            """
        )
        connection.executemany(
            "INSERT INTO images (image_id, name) VALUES (?, ?)",
            [(index, f"image_{index:03d}.jpg") for index in range(1, 4)],
        )
        connection.executemany(
            "INSERT INTO keypoints (image_id, rows) VALUES (?, ?)",
            [(index, 400) for index in range(1, 4)],
        )
        connection.executemany(
            "INSERT INTO two_view_geometries (pair_id, rows, cols, config) VALUES (?, ?, ?, ?)",
            [
                (1 * COLMAP_MAX_IMAGES + 2, 100, 2, 3),
                (2 * COLMAP_MAX_IMAGES + 3, 80, 2, 3),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    stats = read_database_stats(path)
    assert stats.images == 3
    assert stats.keypoints == 1200
    assert stats.verified_pairs == 2
    assert stats.components == 1
    assert stats.largest_component == 3
