"""Add match_type to season_match for round-robin tournament scheduling

Revision ID: p2q3r4s5t6u7
Revises: o1p2q3r4s5t6
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'p2q3r4s5t6u7'
down_revision = 'o1p2q3r4s5t6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('season_match', schema=None) as batch_op:
        batch_op.add_column(sa.Column('match_type', sa.String(20), server_default='regular', nullable=True))


def downgrade():
    with op.batch_alter_table('season_match', schema=None) as batch_op:
        batch_op.drop_column('match_type')
