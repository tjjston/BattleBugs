"""Add user role, elo and management fields

Revision ID: d9e7a1b2f456
Revises: c4f8b9d6a123
Create Date: 2025-11-17 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd9e7a1b2f456'
down_revision = 'c4f8b9d6a123'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('elo', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('is_banned', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('warnings', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('comments_made', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('tournaments_participated', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('tournaments_won', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('bugs_submitted', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('best_bug_elo', sa.Integer(), nullable=True))

    # Optional: set defaults for existing users
    try:
        op.execute("UPDATE user SET role='USER' WHERE role IS NULL")
        op.execute("UPDATE user SET elo=1000 WHERE elo IS NULL")
        op.execute("UPDATE user SET is_active=1 WHERE is_active IS NULL")
        op.execute("UPDATE user SET is_banned=0 WHERE is_banned IS NULL")
    except Exception:
        # Best-effort; ignore failures in some DBs/environments
        pass


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('best_bug_elo')
        batch_op.drop_column('bugs_submitted')
        batch_op.drop_column('tournaments_won')
        batch_op.drop_column('tournaments_participated')
        batch_op.drop_column('comments_made')
        batch_op.drop_column('warnings')
        batch_op.drop_column('is_banned')
        batch_op.drop_column('is_active')
        batch_op.drop_column('elo')
        batch_op.drop_column('role')
