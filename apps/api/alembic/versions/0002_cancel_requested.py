"""add the cancellation flag to the task table

Revision ID: 0002_cancel_requested
Revises: 0001_initial_schema
Create Date: 2026-10-21

The flag lets an operator stop a running browser job: the workflow checks it
between its steps and closes the browser instead of being killed.

The initial revision creates the schema from the SQLAlchemy metadata, so a
freshly created database already contains the column.  The migration is
therefore written defensively and only adds what is really missing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_cancel_requested"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

COLUMN = "cancel_requested"
INDEX = "ix_tasks_cancel_requested"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    if COLUMN not in columns:
        # Plain statements instead of the batch mode: the reflection of the
        # "tasks" table trips a circular dependency check in SQLAlchemy 2.1.
        op.execute(f"ALTER TABLE tasks ADD COLUMN {COLUMN} BOOLEAN NOT NULL DEFAULT 0")
    indexes = {index["name"] for index in inspector.get_indexes("tasks")}
    if INDEX not in indexes:
        op.create_index(INDEX, "tasks", [COLUMN])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("tasks")}
    if INDEX in indexes:
        op.drop_index(INDEX, table_name="tasks")
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    if COLUMN in columns:
        op.execute(f"ALTER TABLE tasks DROP COLUMN {COLUMN}")
