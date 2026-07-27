"""Add catalog requests table

Revision ID: d519307f4f7c
Revises: 3a0d59f69f6d
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd519307f4f7c'
down_revision: Union[str, Sequence[str], None] = '3a0d59f69f6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'data_catalog_requests',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
        sa.Column('thread_id', sa.String(100), nullable=False),
        sa.Column('tracking_number', sa.String(100), nullable=False, unique=True),
        sa.Column('tipo', sa.String(20), nullable=False),
        sa.Column('producto_nombre', sa.String(255), nullable=True),
        sa.Column('producto_sku', sa.String(100), nullable=True),
        sa.Column('cantidad', sa.Integer(), nullable=True),
        sa.Column('fecha_entrega', sa.String(20), nullable=True),
        sa.Column('contact_data', sa.Text(), nullable=True),
        sa.Column('pdf_path', sa.String(255), nullable=True),
        sa.Column('status', sa.String(50), nullable=True, server_default='Pendiente'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('data_catalog_requests')
