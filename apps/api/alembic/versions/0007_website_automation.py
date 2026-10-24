"""the per website automation configuration

Revision ID: 0007_website_automation
Revises: 0006_profile_address
Create Date: 2026-10-24

A project can contain several directories, and each directory has a different
submission form.  The old ``adapter_configurations`` table stores one
configuration per project and adapter, so every form of the project shared the
same selectors.  The new column keeps the form URL, the selector mapping and
the success signal next to the website itself.

The baseline revision creates the schema from the SQLAlchemy metadata, so this
migration is defensive and only adds the column when it is missing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_website_automation"
down_revision = "0006_profile_address"
branch_labels = None
depends_on = None

TABLE = "websites"
COLUMN = "adapter_config"


def upgrade() -> None:
    """Add the nullable JSON column with the per website adapter config."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN not in columns:
        op.add_column(TABLE, sa.Column(COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove the per website adapter config."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN in columns:
        op.drop_column(TABLE, COLUMN)
