"""

Revision ID: 0334_update_template

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = '0333_update_template'


def upgrade():
    op.add_column('template', sa.Column('communication_item', postgresql.UUID, nullable=True))


def downgrade():
    op.drop_column('template', 'communication_item')
