"""add indexes for submission_date and battle_date

Revision ID: r4s5t6u7v8w9
Revises: q3r4s5t6u7v8
Create Date: 2026-04-28
"""
from alembic import op

revision = 'r4s5t6u7v8w9'
down_revision = 'q3r4s5t6u7v8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bug') as batch_op:
        batch_op.create_index('ix_bug_submission_date', ['submission_date'])

    with op.batch_alter_table('battle') as batch_op:
        batch_op.create_index('ix_battle_battle_date', ['battle_date'])


def downgrade():
    with op.batch_alter_table('bug') as batch_op:
        batch_op.drop_index('ix_bug_submission_date')

    with op.batch_alter_table('battle') as batch_op:
        batch_op.drop_index('ix_battle_battle_date')
