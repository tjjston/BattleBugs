"""add bug.life_stage column for life-cycle aware classification

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2026-05-18

"""
from alembic import op
import sqlalchemy as sa


revision = 'y2z3a4b5c6d7'
down_revision = 'x1y2z3a4b5c6'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing = [c['name'] for c in sa.inspect(conn).get_columns('bug')]
    if 'life_stage' not in existing:
        with op.batch_alter_table('bug', schema=None) as batch_op:
            batch_op.add_column(sa.Column('life_stage', sa.String(20), nullable=True))


def downgrade():
    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.drop_column('life_stage')
