"""Add lethality/grip/cunning stats to Bug and per-side win counts to BugRival

Revision ID: h4i5j6k7l8m9
Revises: g3h4i5j6k7l8
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'h4i5j6k7l8m9'
down_revision = 'g3h4i5j6k7l8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lethality', sa.Integer(), nullable=True, server_default='50'))
        batch_op.add_column(sa.Column('grip', sa.Integer(), nullable=True, server_default='50'))
        batch_op.add_column(sa.Column('cunning', sa.Integer(), nullable=True, server_default='50'))

    with op.batch_alter_table('bug_rival', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bug1_wins', sa.Integer(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('bug2_wins', sa.Integer(), nullable=True, server_default='0'))


def downgrade():
    with op.batch_alter_table('bug_rival', schema=None) as batch_op:
        batch_op.drop_column('bug2_wins')
        batch_op.drop_column('bug1_wins')

    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.drop_column('cunning')
        batch_op.drop_column('grip')
        batch_op.drop_column('lethality')
