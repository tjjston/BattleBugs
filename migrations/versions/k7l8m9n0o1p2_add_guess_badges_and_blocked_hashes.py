"""Add species-guess counters to User and blocked_image_hash table

Revision ID: k7l8m9n0o1p2
Revises: j6k7l8m9n0o1
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'k7l8m9n0o1p2'
down_revision = 'j6k7l8m9n0o1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('total_guesses',   sa.Integer(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('correct_guesses', sa.Integer(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('skipped_guesses', sa.Integer(), nullable=True, server_default='0'))

    op.create_table(
        'blocked_image_hash',
        sa.Column('id',         sa.Integer(),     primary_key=True),
        sa.Column('image_hash', sa.String(64),    nullable=False, unique=True),
        sa.Column('reason',     sa.String(100),   server_default='zombug_failed'),
        sa.Column('created_at', sa.DateTime()),
    )
    op.create_index('ix_blocked_image_hash_image_hash', 'blocked_image_hash', ['image_hash'])


def downgrade():
    op.drop_index('ix_blocked_image_hash_image_hash', 'blocked_image_hash')
    op.drop_table('blocked_image_hash')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('skipped_guesses')
        batch_op.drop_column('correct_guesses')
        batch_op.drop_column('total_guesses')
