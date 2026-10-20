"""Initial schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2024-01-01 00:00:00.000000

The baseline revision creates the complete schema on SQLite (local / desktop
mode) *and* PostgreSQL (cloud mode).  Instead of hand written DDL for every
table the migration delegates to the SQLAlchemy metadata, which keeps the
schema identical to the models no matter which dialect is used::

    Base.metadata.create_all(bind=op.get_bind())

``downgrade()`` removes the tables again.  The ``alembic_version`` table is
managed by Alembic itself and is not touched here.

Note: because the revision uses the metadata it cannot be rendered offline
(``alembic upgrade head --sql``).  Use ``alembic upgrade head`` against a
real database instead.
"""

from __future__ import annotations

from alembic import op

from app.db.base import Base

# Importing the models registers every table on ``Base.metadata``.
import app.db.models  # noqa: F401  isort:skip

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create every table of the application schema."""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop every table of the application schema."""
    Base.metadata.drop_all(bind=op.get_bind())
