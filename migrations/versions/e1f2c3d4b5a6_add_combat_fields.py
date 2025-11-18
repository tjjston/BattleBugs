"""Add combat fields to Bug model

Revision ID: e1f2c3d4b5a6
Revises: d9e7a1b2f456
Create Date: 2025-11-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e1f2c3d4b5a6'
down_revision = 'd9e7a1b2f456'
branch_labels = None
depends_on = None


def upgrade():
    # Add nullable columns so existing DBs upgrade non-interactively
    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.add_column(sa.Column('attack_type', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('defense_type', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('size_class', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('bug', schema=None) as batch_op:
        batch_op.drop_column('size_class')
        batch_op.drop_column('defense_type')
        batch_op.drop_column('attack_type')
