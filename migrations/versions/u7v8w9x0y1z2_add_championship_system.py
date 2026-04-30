"""add championship system

Revision ID: u7v8w9x0y1z2
Revises: t6u7v8w9x0y1
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa

revision = 'u7v8w9x0y1z2'
down_revision = 't6u7v8w9x0y1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bug_track', sa.String(20), nullable=True))

    op.create_table(
        'tier_championship',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('tier', sa.String(20), nullable=False, unique=True),
        sa.Column('champion_bug_id', sa.Integer, sa.ForeignKey('bug.id'), nullable=True),
        sa.Column('won_date', sa.DateTime, nullable=True),
        sa.Column('defense_count', sa.Integer, default=0),
        sa.Column('next_defense_due', sa.DateTime, nullable=True),
        sa.Column('status', sa.String(20), default='vacant'),
    )
    op.create_table(
        'tier_ranking',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('tier', sa.String(20), nullable=False),
        sa.Column('bug_id', sa.Integer, sa.ForeignKey('bug.id'), nullable=False),
        sa.Column('rank', sa.Integer, nullable=True),
        sa.Column('ranking_score', sa.Float, default=0.0),
        sa.Column('last_updated', sa.DateTime, nullable=True),
        sa.Column('last_fight_date', sa.DateTime, nullable=True),
        sa.UniqueConstraint('tier', 'bug_id', name='uq_tier_bug_ranking'),
    )
    op.create_table(
        'title_fight',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('tier', sa.String(20), nullable=False),
        sa.Column('championship_id', sa.Integer, sa.ForeignKey('tier_championship.id'), nullable=False),
        sa.Column('challenger_bug_id', sa.Integer, sa.ForeignKey('bug.id'), nullable=True),
        sa.Column('scheduled_date', sa.DateTime, nullable=False),
        sa.Column('bid_closes_at', sa.DateTime, nullable=False),
        sa.Column('status', sa.String(20), default='bidding'),
        sa.Column('battle_id', sa.Integer, sa.ForeignKey('battle.id'), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=True),
    )
    op.create_table(
        'title_bid',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('fight_id', sa.Integer, sa.ForeignKey('title_fight.id'), nullable=False),
        sa.Column('bug_id', sa.Integer, sa.ForeignKey('bug.id'), nullable=False),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('user.id'), nullable=False),
        sa.Column('amount', sa.Integer, nullable=False),
        sa.Column('contender_rank', sa.Integer, nullable=False),
        sa.Column('min_required', sa.Integer, nullable=False),
        sa.Column('placed_at', sa.DateTime, nullable=True),
        sa.Column('won_bid', sa.Boolean, default=False),
        sa.UniqueConstraint('fight_id', 'bug_id', name='uq_fight_bug_bid'),
    )
    op.create_table(
        'contender_callout',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('tier', sa.String(20), nullable=False),
        sa.Column('challenger_bug_id', sa.Integer, sa.ForeignKey('bug.id'), nullable=False),
        sa.Column('target_bug_id', sa.Integer, sa.ForeignKey('bug.id'), nullable=False),
        sa.Column('status', sa.String(20), default='pending'),
        sa.Column('created_at', sa.DateTime, nullable=True),
        sa.Column('expires_at', sa.DateTime, nullable=False),
        sa.Column('battle_id', sa.Integer, sa.ForeignKey('battle.id'), nullable=True),
    )


def downgrade():
    op.drop_table('contender_callout')
    op.drop_table('title_bid')
    op.drop_table('title_fight')
    op.drop_table('tier_ranking')
    op.drop_table('tier_championship')
    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.drop_column('bug_track')
