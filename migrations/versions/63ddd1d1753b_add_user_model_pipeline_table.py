"""Add per-user model pipeline configuration.

Revision ID: 63ddd1d1753b
Revises:
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "63ddd1d1753b"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_model_pipelines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("main_model", sa.String(length=100), nullable=True),
        sa.Column("model_type_preference", sa.String(length=20), nullable=True),
        sa.Column("step_models", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_model_pipelines_user_id"),
        "user_model_pipelines",
        ["user_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_user_model_pipelines_user_id"),
        table_name="user_model_pipelines",
    )
    op.drop_table("user_model_pipelines")
