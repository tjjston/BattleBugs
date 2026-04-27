"""Add jobs, bug enrichment status, and vote tracking

Revision ID: f2a3b4c5d6e7
Revises: e1f2c3d4b5a6
Create Date: 2026-04-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2c3d4b5a6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.add_column(sa.Column('enrichment_status', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('enrichment_error', sa.Text(), nullable=True))

    op.create_table(
        'job',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=80), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=True),
        sa.Column('result_json', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_job_status'), 'job', ['status'], unique=False)
    op.create_index(op.f('ix_job_type'), 'job', ['type'], unique=False)

    op.create_table(
        'comment_vote',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('comment_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['comment_id'], ['comment.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('comment_id', 'user_id', name='uq_comment_vote_user')
    )

    op.create_table(
        'bug_lore_vote',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lore_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['lore_id'], ['bug_lore.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('lore_id', 'user_id', name='uq_lore_vote_user')
    )


def downgrade():
    op.drop_table('bug_lore_vote')
    op.drop_table('comment_vote')
    op.drop_index(op.f('ix_job_type'), table_name='job')
    op.drop_index(op.f('ix_job_status'), table_name='job')
    op.drop_table('job')

    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.drop_column('enrichment_error')
        batch_op.drop_column('enrichment_status')
