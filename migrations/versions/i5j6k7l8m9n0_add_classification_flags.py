"""Add classification_flag table for user dispute requests

Revision ID: i5j6k7l8m9n0
Revises: h4i5j6k7l8m9
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = 'i5j6k7l8m9n0'
down_revision = 'h4i5j6k7l8m9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'classification_flag',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bug_id', sa.Integer(), sa.ForeignKey('bug.id'), nullable=False),
        sa.Column('flagging_user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('suggested_species', sa.String(200)),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('reviewed_at', sa.DateTime()),
        sa.Column('reviewer_id', sa.Integer(), sa.ForeignKey('user.id')),
        sa.Column('reviewer_notes', sa.Text()),
        sa.UniqueConstraint('bug_id', 'flagging_user_id', name='uq_flag_per_user_per_bug'),
    )


def downgrade():
    op.drop_table('classification_flag')
