"""add bug.ability_slug column for canonical ability resolution

Revision ID: x1y2z3a4b5c6
Revises: w0x1y2z3a4b5
Create Date: 2026-05-16

"""
from alembic import op
import sqlalchemy as sa


revision = 'x1y2z3a4b5c6'
down_revision = 'w0x1y2z3a4b5'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing = [c['name'] for c in sa.inspect(conn).get_columns('bug')]
    if 'ability_slug' not in existing:
        with op.batch_alter_table('bug', schema=None) as batch_op:
            batch_op.add_column(sa.Column('ability_slug', sa.String(80), nullable=True))


def downgrade():
    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.drop_column('ability_slug')
