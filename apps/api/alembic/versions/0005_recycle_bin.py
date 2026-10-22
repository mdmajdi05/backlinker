"""the recycle bin: a deleted row waits until it is restored or purged

Revision ID: 0005_recycle_bin
Revises: 0004_website_list
Create Date: 2026-10-22

Deleting a project, a business profile, a website or an opportunity no longer
throws the row away.  The row gets a ``deleted_at`` timestamp, disappears from
the normal endpoints and waits in the recycle bin.  Restoring clears the
timestamp; deleting it forever removes the row (and whatever depends on it).

The baseline revision creates the schema from the SQLAlchemy metadata, so a
freshly created database already contains the columns.  The migration is
therefore written defensively and only adds what is really missing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_recycle_bin"
down_revision = "0004_website_list"
branch_labels = None
depends_on = None

TABLES = ("projects", "business_profiles", "websites", "opportunities")
COLUMN = "deleted_at"
INDEX = "ix_{table}_deleted_at"


def upgrade() -> None:
    """Add the ``deleted_at`` column to every table of the recycle bin."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    for table in TABLES:
        if table not in existing:
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if COLUMN not in columns:
            op.add_column(
                table,
                sa.Column(COLUMN, sa.DateTime(timezone=True), nullable=True),
            )
        indexes = {index["name"] for index in inspector.get_indexes(table)}
        name = INDEX.format(table=table)
        if name not in indexes:
            op.create_index(name, table, [COLUMN])


def downgrade() -> None:
    """Remove the recycle bin columns again."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    for table in TABLES:
        if table not in existing:
            continue
        indexes = {index["name"] for index in inspector.get_indexes(table)}
        name = INDEX.format(table=table)
        if name in indexes:
            op.drop_index(name, table_name=table)
        columns = {column["name"] for column in inspector.get_columns(table)}
        if COLUMN in columns:
            op.drop_column(table, COLUMN)
