"""Add catalog search logs table

Revision ID: f2a9c31e7b4d
Revises: d519307f4f7c
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f2a9c31e7b4d'
down_revision: Union[str, Sequence[str], None] = 'd519307f4f7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'data_catalog_search_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
        sa.Column('thread_id', sa.String(100), nullable=False),
        sa.Column('query', sa.String(255), nullable=False),
        sa.Column('found', sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column('results_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('producto_nombre', sa.String(255), nullable=True),
        sa.Column('producto_sku', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('data_catalog_search_logs')
