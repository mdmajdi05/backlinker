"""per project browser profile and website login sessions

Revision ID: 0008_project_logins
Revises: 0007_website_automation
Create Date: 2026-10-26

The operator connects one Google account per project.  The session lives in an
isolated profile directory and its exported ``storage_state`` is encrypted in
the ``project_login_profiles`` table.  ``website_login_sessions`` remembers
which directory of the project answered with a login wall, so the project can
show "login expired" and resume the paused work after a fresh login.

The baseline migration creates the schema from the SQLAlchemy metadata, so this
migration is defensive and only creates the two tables when they are missing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_project_logins"
down_revision = "0007_website_automation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the login tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "project_login_profiles" not in tables:
        op.create_table(
            "project_login_profiles",
            sa.Column("id", sa.String(length=32), primary_key=True),
            sa.Column(
                "project_id",
                sa.String(length=32),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("provider", sa.String(length=32), nullable=False, server_default="google"),
            sa.Column(
                "status", sa.String(length=24), nullable=False, server_default="NOT_CONNECTED"
            ),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("profile_dir", sa.String(length=800), nullable=False, server_default=""),
            sa.Column("storage_state_encrypted", sa.Text(), nullable=True),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("project_id", name="uq_project_login_profiles_project_id"),
        )
        op.create_index(
            "ix_project_login_profiles_project_id",
            "project_login_profiles",
            ["project_id"],
        )
        op.create_index(
            "ix_project_login_profiles_status",
            "project_login_profiles",
            ["status"],
        )

    if "website_login_sessions" not in tables:
        op.create_table(
            "website_login_sessions",
            sa.Column("id", sa.String(length=32), primary_key=True),
            sa.Column(
                "project_id",
                sa.String(length=32),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "website_id",
                sa.String(length=32),
                sa.ForeignKey("websites.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "status", sa.String(length=24), nullable=False, server_default="UNKNOWN"
            ),
            sa.Column(
                "method", sa.String(length=24), nullable=False, server_default="UNKNOWN"
            ),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "project_id",
                "website_id",
                name="uq_website_login_sessions_project_website",
            ),
        )
        op.create_index(
            "ix_website_login_sessions_project_id",
            "website_login_sessions",
            ["project_id"],
        )
        op.create_index(
            "ix_website_login_sessions_website_id",
            "website_login_sessions",
            ["website_id"],
        )
        op.create_index(
            "ix_website_login_sessions_status",
            "website_login_sessions",
            ["status"],
        )


def downgrade() -> None:
    """Drop the login tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "website_login_sessions" in tables:
        op.drop_table("website_login_sessions")
    if "project_login_profiles" in tables:
        op.drop_table("project_login_profiles")
