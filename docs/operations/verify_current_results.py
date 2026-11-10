#!/usr/bin/env python3
"""Verify that every current result has its stored file with the recorded size.

Post-restore / post-incident consistency check required by
``08_infrastructure.md`` Section 12.5 and used by the Phase 8 backup drill.

Run inside the API container (the storage root must be mounted):

    docker cp docs/operations/verify_current_results.py mogen-api-1:/tmp/verify.py
    docker compose exec -T -e PYTHONPATH=/app api python /tmp/verify.py

Exit code 0 means every current result is backed by a readable file of the
recorded size; 1 means at least one row and file disagree.
"""

from __future__ import annotations

import sys

from app.core.config import get_settings
from app.db.models import GenerationResult, Project
from app.db.session import create_db_engine, create_session_factory
from sqlalchemy import select


def main() -> int:
    settings = get_settings()
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    missing: list[dict[str, str | int]] = []
    checked = 0
    with factory() as session:
        # A soft-deleted project's tree is removed by the cleanup worker, so its
        # historical result rows intentionally have no file. Only active
        # projects must be backed by a stored asset.
        results = session.scalars(
            select(GenerationResult)
            .join(Project, Project.id == GenerationResult.project_id)
            .where(GenerationResult.is_current.is_(True), Project.deleted_at.is_(None))
        ).all()
        for result in results:
            checked += 1
            path = settings.storage_root / result.storage_key
            if not path.is_file():
                missing.append({"result_id": str(result.id), "reason": "missing"})
            elif path.stat().st_size != result.file_size_bytes:
                missing.append(
                    {
                        "result_id": str(result.id),
                        "reason": "size_mismatch",
                        "expected": result.file_size_bytes,
                        "actual": path.stat().st_size,
                    }
                )
    print({"checked_current_results": checked, "missing_or_mismatched": missing})
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
