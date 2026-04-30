"""add species taxonomy enrichment fields (CoL ID, conservation status, obs count)

Revision ID: v9w0x1y2z3a4
Revises: u7v8w9x0y1z2
Create Date: 2026-04-29

"""
from alembic import op
import sqlalchemy as sa

revision = 'v9w0x1y2z3a4'
down_revision = 'u7v8w9x0y1z2'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing = [c['name'] for c in sa.inspect(conn).get_columns('species')]
    new_cols = {
        'catalogue_of_life_id': sa.Column('catalogue_of_life_id', sa.String(100), nullable=True),
        'conservation_status': sa.Column('conservation_status', sa.String(50), nullable=True),
        'observation_count': sa.Column('observation_count', sa.Integer(), nullable=True),
        'gbif_backbone_key': sa.Column('gbif_backbone_key', sa.Integer(), nullable=True),
        'accepted_name': sa.Column('accepted_name', sa.String(200), nullable=True),
    }
    with op.batch_alter_table('species', schema=None) as batch_op:
        for col_name, col_def in new_cols.items():
            if col_name not in existing:
                batch_op.add_column(col_def)


def downgrade():
    with op.batch_alter_table('species', schema=None) as batch_op:
        for col in ('catalogue_of_life_id', 'conservation_status', 'observation_count',
                    'gbif_backbone_key', 'accepted_name'):
            batch_op.drop_column(col)
