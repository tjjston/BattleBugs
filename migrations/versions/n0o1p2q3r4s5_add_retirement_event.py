"""Add tournament.retirement_event flag

Revision ID: n0o1p2q3r4s5
Revises: m9n0o1p2q3r4
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'n0o1p2q3r4s5'
down_revision = 'm9n0o1p2q3r4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tournament', schema=None) as batch_op:
        batch_op.add_column(sa.Column('retirement_event', sa.Boolean(), server_default='0', nullable=True))


def downgrade():
    with op.batch_alter_table('tournament', schema=None) as batch_op:
        batch_op.drop_column('retirement_event')
