"""Add system_setting table for admin runtime configuration

Revision ID: l8m9n0o1p2q3
Revises: k7l8m9n0o1p2
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'l8m9n0o1p2q3'
down_revision = 'k7l8m9n0o1p2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'system_setting',
        sa.Column('key',           sa.String(64),  primary_key=True),
        sa.Column('value',         sa.Text(),       nullable=False),
        sa.Column('updated_at',    sa.DateTime()),
        sa.Column('updated_by_id', sa.Integer(),    sa.ForeignKey('user.id'), nullable=True),
    )


def downgrade():
    op.drop_table('system_setting')
