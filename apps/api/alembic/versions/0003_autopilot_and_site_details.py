"""add the site details table and the auto pilot settings

Revision ID: 0003_autopilot_and_site_details
Revises: 0002_cancel_requested
Create Date: 2026-10-21

The migration adds

* the ``site_details`` table - the structured values a directory asks for,
  stored per opportunity, and
* the ``auto_submit`` / ``auto_submit_categories`` columns of
  ``project_settings`` - the auto pilot that keeps submitting.

The baseline revision creates the schema from the SQLAlchemy metadata, so a
freshly created database already contains everything.  The migration is
therefore written defensively and only adds what is really missing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.models import SiteDetails

revision = "0003_autopilot_and_site_details"
down_revision = "0002_cancel_requested"
branch_labels = None
depends_on = None

TABLE = "site_details"
SETTINGS_TABLE = "project_settings"
AUTO_SUBMIT = "auto_submit"
AUTO_SUBMIT_CATEGORIES = "auto_submit_categories"


def upgrade() -> None:
    """Create the site details table and add the auto pilot columns."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = set(inspector.get_table_names())
    if TABLE not in tables:
        SiteDetails.__table__.create(bind=bind, checkfirst=True)
        inspector = sa.inspect(bind)

    if SETTINGS_TABLE not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns(SETTINGS_TABLE)}
    if AUTO_SUBMIT not in columns:
        op.add_column(
            SETTINGS_TABLE,
            sa.Column(
                AUTO_SUBMIT,
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if AUTO_SUBMIT_CATEGORIES not in columns:
        op.add_column(
            SETTINGS_TABLE,
            sa.Column(AUTO_SUBMIT_CATEGORIES, sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    """Remove the site details table and the auto pilot columns."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if SETTINGS_TABLE in set(inspector.get_table_names()):
        columns = {column["name"] for column in inspector.get_columns(SETTINGS_TABLE)}
        for column in (AUTO_SUBMIT_CATEGORIES, AUTO_SUBMIT):
            if column in columns:
                op.drop_column(SETTINGS_TABLE, column)

    if TABLE in set(inspector.get_table_names()):
        SiteDetails.__table__.drop(bind=bind, checkfirst=True)
