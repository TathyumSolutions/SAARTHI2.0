"""Add company_name to app_users and create response_feedback table

Revision ID: 20260728_01
Revises: 
Create Date: 2026-07-28 15:05:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260728_01'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('app_users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('company_name', sa.String(length=150), nullable=True))
        batch_op.create_index('ix_app_users_company_name', ['company_name'], unique=False)

    op.create_table(
        'response_feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('company_name', sa.String(length=150), nullable=True),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('sql_query', sa.Text(), nullable=True),
        sa.Column('router_decision', sa.String(length=50), nullable=True),
        sa.Column('feedback_type', sa.String(length=10), nullable=False),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('metamind_snapshot', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['app_users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_response_feedback_company_name', 'response_feedback', ['company_name'], unique=False)
    op.create_index('ix_response_feedback_created_at', 'response_feedback', ['created_at'], unique=False)


def downgrade():
    op.drop_index('ix_response_feedback_created_at', table_name='response_feedback')
    op.drop_index('ix_response_feedback_company_name', table_name='response_feedback')
    op.drop_table('response_feedback')

    with op.batch_alter_table('app_users', schema=None) as batch_op:
        batch_op.drop_index('ix_app_users_company_name')
        batch_op.drop_column('company_name')
