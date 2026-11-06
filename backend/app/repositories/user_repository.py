"""Repository for user accounts (05_database_specification.md Section 5)."""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Database access for user accounts.

    Email normalization is a service rule (Section 5.2); this repository
    compares the stored value exactly as given.
    """

    model = User

    def create(
        self,
        *,
        email: str,
        password_hash: str,
        is_active: bool = True,
    ) -> User:
        """Insert a user. A duplicate email raises ``IntegrityError``."""
        return self.add(User(email=email, password_hash=password_hash, is_active=is_active))

    def get_by_email(self, email: str) -> User | None:
        """Return the user with this email, or ``None``."""
        return self.session.scalar(select(User).where(User.email == email))
