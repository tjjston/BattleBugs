"""Add bug condition fields and notification table

Revision ID: j6k7l8m9n0o1
Revises: i5j6k7l8m9n0
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'j6k7l8m9n0o1'
down_revision = 'i5j6k7l8m9n0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_zombug', sa.Boolean(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('condition', sa.String(30), nullable=True, server_default='alive'))
        batch_op.add_column(sa.Column('condition_notes', sa.Text(), nullable=True))

    op.create_table(
        'notification',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('link_url', sa.String(500)),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime()),
    )


def downgrade():
    op.drop_table('notification')

    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.drop_column('condition_notes')
        batch_op.drop_column('condition')
        batch_op.drop_column('is_zombug')
