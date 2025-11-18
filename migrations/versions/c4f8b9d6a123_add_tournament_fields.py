"""Add tournament created_at, registration_deadline, created_by_id

Revision ID: c4f8b9d6a123
Revises: abd2824ef3fa
Create Date: 2025-11-17 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4f8b9d6a123'
down_revision = 'abd2824ef3fa'
branch_labels = None
depends_on = None


def upgrade():
    # Add nullable columns so upgrade is non-blocking for existing data
    with op.batch_alter_table('tournament', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('registration_deadline', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('created_by_id', sa.Integer(), nullable=True))

    # Create a foreign key constraint for created_by_id -> user.id if user table exists
    try:
        op.create_foreign_key(
            'fk_tournament_created_by', 'tournament', 'user', ['created_by_id'], ['id']
        )
    except Exception:
        # If creating the FK fails (e.g., target table missing in some environments),
        # leave the column without FK and let the DBA handle constraints.
        pass


def downgrade():
    # Drop FK if exists, then drop columns
    try:
        op.drop_constraint('fk_tournament_created_by', 'tournament', type_='foreignkey')
    except Exception:
        pass

    with op.batch_alter_table('tournament', schema=None) as batch_op:
        batch_op.drop_column('created_by_id')
        batch_op.drop_column('registration_deadline')
        batch_op.drop_column('created_at')
