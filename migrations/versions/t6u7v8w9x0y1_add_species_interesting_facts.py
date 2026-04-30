"""add species interesting_facts

Revision ID: t6u7v8w9x0y1
Revises: s5t6u7v8w9x0
Create Date: 2026-04-29

"""
from alembic import op
import sqlalchemy as sa

revision = 't6u7v8w9x0y1'
down_revision = 's5t6u7v8w9x0'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing = [c['name'] for c in sa.inspect(conn).get_columns('species')]
    if 'interesting_facts' not in existing:
        with op.batch_alter_table('species', schema=None) as batch_op:
            batch_op.add_column(sa.Column('interesting_facts', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('species', schema=None) as batch_op:
        batch_op.drop_column('interesting_facts')
