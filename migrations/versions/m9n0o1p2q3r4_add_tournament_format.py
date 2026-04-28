"""Add tournament.format and submissions_per_user

Revision ID: m9n0o1p2q3r4
Revises: l8m9n0o1p2q3
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'm9n0o1p2q3r4'
down_revision = 'l8m9n0o1p2q3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tournament', schema=None) as batch_op:
        batch_op.add_column(sa.Column('format', sa.String(30), server_default='single_elimination', nullable=True))
        batch_op.add_column(sa.Column('submissions_per_user', sa.Integer(), server_default='2', nullable=True))


def downgrade():
    with op.batch_alter_table('tournament', schema=None) as batch_op:
        batch_op.drop_column('submissions_per_user')
        batch_op.drop_column('format')
