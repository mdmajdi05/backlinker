"""add the niche to the central website list

Revision ID: 0004_website_list
Revises: 0003_autopilot_and_site_details
Create Date: 2026-10-21

The central list of websites can be filtered by a niche (free text) beside
the category, therefore the ``websites`` table gets a ``niche`` column.

The baseline revision creates the schema from the SQLAlchemy metadata, so a
freshly created database already contains the column.  The migration is
therefore written defensively and only adds what is really missing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_website_list"
down_revision = "0003_autopilot_and_site_details"
branch_labels = None
depends_on = None

TABLE = "websites"
COLUMN = "niche"
INDEX = "ix_websites_niche"


def upgrade() -> None:
    """Add the niche column (and its index) to the websites table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN not in columns:
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN,
                sa.String(length=160),
                nullable=False,
                server_default=sa.text("''"),
            ),
        )
    indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    if INDEX not in indexes:
        op.create_index(INDEX, TABLE, [COLUMN])


def downgrade() -> None:
    """Remove the niche column (and its index) again."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return

    indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    if INDEX in indexes:
        op.drop_index(INDEX, table_name=TABLE)
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN in columns:
        op.drop_column(TABLE, COLUMN)
