"""add bug.stats_reasoning column for per-stat LLM explanation

Revision ID: w0x1y2z3a4b5
Revises: v9w0x1y2z3a4
Create Date: 2026-05-16

"""
from alembic import op
import sqlalchemy as sa


revision = 'w0x1y2z3a4b5'
down_revision = 'v9w0x1y2z3a4'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing = [c['name'] for c in sa.inspect(conn).get_columns('bug')]
    if 'stats_reasoning' not in existing:
        with op.batch_alter_table('bug', schema=None) as batch_op:
            batch_op.add_column(sa.Column('stats_reasoning', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.drop_column('stats_reasoning')
