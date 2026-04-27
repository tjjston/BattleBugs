"""Add accolade points economy

Revision ID: a1b2c3d4e5f8
Revises: f2a3b4c5d6e7
Create Date: 2026-04-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f8'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('accolade_points', sa.Integer(), nullable=True))

    op.execute('UPDATE "user" SET accolade_points = 0 WHERE accolade_points IS NULL')

    op.create_table(
        'currency_transaction',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=120), nullable=False),
        sa.Column('reference_type', sa.String(length=50), nullable=True),
        sa.Column('reference_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_currency_transaction_user_id'), 'currency_transaction', ['user_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_currency_transaction_user_id'), table_name='currency_transaction')
    op.drop_table('currency_transaction')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('accolade_points')
