"""Shared repository behaviour.

Repositories encapsulate SQL and never commit: the calling service owns the
transaction boundary (05_database_specification.md Section 19.3). A repository
only flushes so that generated identifiers, timestamps and constraint errors
are available inside that transaction.
"""

from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from sqlalchemy.orm import Session

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Base class for repositories bound to one database session."""

    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, entity_id: uuid.UUID) -> ModelT | None:
        """Return an entity by primary key, or ``None`` when it does not exist."""
        return self.session.get(self.model, entity_id)

    def add(self, instance: ModelT) -> ModelT:
        """Persist a new entity inside the current transaction."""
        self.session.add(instance)
        self.session.flush()
        return instance

    def delete(self, instance: ModelT) -> None:
        """Delete an entity inside the current transaction."""
        self.session.delete(instance)
        self.session.flush()
