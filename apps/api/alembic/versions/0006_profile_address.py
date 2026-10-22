"""the company address of a business profile

Revision ID: 0006_profile_address
Revises: 0005_recycle_bin
Create Date: 2026-10-22

A directory submission asks for the address of the company.  The business
profile had no place for it, so the details could never be derived from the
profile and the operator had to type them again for every website.  These
columns are that one place.

The baseline revision creates the schema from the SQLAlchemy metadata, so a
freshly created database already contains the columns.  The migration is
therefore written defensively and only adds what is really missing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_profile_address"
down_revision = "0005_recycle_bin"
branch_labels = None
depends_on = None

TABLE = "business_profiles"
TEXT_COLUMNS = ("address", "city", "state", "country", "postal_code")
NUMBER_COLUMNS = ("founded_year", "employee_count")


def upgrade() -> None:
    """Add the address (and the company size) to the business profile."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    for name in TEXT_COLUMNS:
        if name not in columns:
            op.add_column(
                TABLE,
                sa.Column(name, sa.String(length=255), nullable=False, server_default=sa.text("''")),
            )
    for name in NUMBER_COLUMNS:
        if name not in columns:
            op.add_column(TABLE, sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    """Remove the address columns again."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    for name in NUMBER_COLUMNS + TEXT_COLUMNS:
        if name in columns:
            op.drop_column(TABLE, name)
