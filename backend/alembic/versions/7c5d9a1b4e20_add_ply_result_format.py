"""Allow the PLY asset format for the opt-in Gaussian-splat representation.

Increment 15 registers a Nerfstudio Splatfacto Gaussian PLY as a distinct result
representation. The change is additive and forward-only: the existing ``GLB``,
``OBJ`` and ``STL`` values stay permitted, no row is rewritten and no column or
type changes. Downgrading restores the narrower CHECK constraint and is only
possible while no PLY result exists.

Revision ID: 7c5d9a1b4e20
Revises: 1f302d830cf9
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "7c5d9a1b4e20"
down_revision: str | None = "1f302d830cf9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_generation_results_format"
_TABLE = "generation_results"
_PREVIOUS = "format IN ('GLB', 'OBJ', 'STL')"
_EXTENDED = "format IN ('GLB', 'OBJ', 'STL', 'PLY')"


def upgrade() -> None:
    op.drop_constraint(op.f(_CONSTRAINT), _TABLE, type_="check")
    op.create_check_constraint(op.f(_CONSTRAINT), _TABLE, _EXTENDED)


def downgrade() -> None:
    op.drop_constraint(op.f(_CONSTRAINT), _TABLE, type_="check")
    op.create_check_constraint(op.f(_CONSTRAINT), _TABLE, _PREVIOUS)
