"""add battle venue and rating

Revision ID: q3r4s5t6u7v8
Revises: p2q3r4s5t6u7
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'q3r4s5t6u7v8'
down_revision = 'p2q3r4s5t6u7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('battle') as batch_op:
        batch_op.add_column(sa.Column('venue', sa.String(100), nullable=True))
        batch_op.add_column(sa.Column('battle_rating', sa.String(30), nullable=True))


def downgrade():
    with op.batch_alter_table('battle') as batch_op:
        batch_op.drop_column('battle_rating')
        batch_op.drop_column('venue')
