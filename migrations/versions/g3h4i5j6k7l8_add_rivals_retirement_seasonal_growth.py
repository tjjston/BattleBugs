"""Add BugRival, retirement fields, season_key, and stat_growth

Revision ID: g3h4i5j6k7l8
Revises: f2a3b4c5d6e7
Branch labels: None
Depends on: None

"""
from alembic import op
import sqlalchemy as sa


revision = 'g3h4i5j6k7l8'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    # Bug retirement fields
    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_retired', sa.Boolean(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('retired_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('stat_growth', sa.Integer(), nullable=True, server_default='0'))

    # Tournament seasonal key
    with op.batch_alter_table('tournament', schema=None) as batch_op:
        batch_op.add_column(sa.Column('season_key', sa.String(length=20), nullable=True))

    # BugRival table
    op.create_table(
        'bug_rival',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bug1_id', sa.Integer(), nullable=False),
        sa.Column('bug2_id', sa.Integer(), nullable=False),
        sa.Column('encounter_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_encounter_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['bug1_id'], ['bug.id']),
        sa.ForeignKeyConstraint(['bug2_id'], ['bug.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('bug1_id', 'bug2_id', name='uq_rival_pair'),
    )


def downgrade():
    op.drop_table('bug_rival')

    with op.batch_alter_table('tournament', schema=None) as batch_op:
        batch_op.drop_column('season_key')

    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.drop_column('stat_growth')
        batch_op.drop_column('retired_at')
        batch_op.drop_column('is_retired')
