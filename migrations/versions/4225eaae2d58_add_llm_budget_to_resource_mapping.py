"""Add daily_budget/budget_currency to resource_mapping, and 'llm' as a
resource_type, for the LLM Connections feature.

Only resource_mapping is covered here: it lives in the 'core' bind, which
is this project's default SQLALCHEMY_DATABASE_URI and the only database
migrations/env.py's plain `flask db upgrade` actually reaches. The new
llm_connections table ('resources' bind) and llm_call_logs.llm_connection_id
column ('workspace' bind) are picked up automatically by this app's own
db.create_all() / sync_missing_columns() bootstrap on next startup (see
app/services/db_bootstrap.py) - the same way every other 'resources'/
'workspace' table and column in this codebase is created, since this
single-bind Alembic setup has no revision chain for those databases.

Revision ID: 4225eaae2d58
Revises: 63ddd1d1753b
Create Date: 2026-09-12
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4225eaae2d58"
down_revision = "63ddd1d1753b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("resource_mapping", sa.Column("daily_budget", sa.Numeric(10, 2), nullable=True))
    op.add_column(
        "resource_mapping",
        sa.Column("budget_currency", sa.String(length=3), nullable=False, server_default="USD"),
    )


def downgrade():
    op.drop_column("resource_mapping", "budget_currency")
    op.drop_column("resource_mapping", "daily_budget")
