"""Add pricing tables (client pricing, history, simulations)

Revision ID: d8a3c5f2b7e1
Revises: c7f2b4a1e6d3
Create Date: 2026-07-31 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd8a3c5f2b7e1'
down_revision: Union[str, Sequence[str], None] = 'c7f2b4a1e6d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'adm_client_pricing',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False, unique=True),
        sa.Column('abono_usd', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'adm_client_pricing_history',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
        sa.Column('old_abono_usd', sa.Float(), nullable=True),
        sa.Column('new_abono_usd', sa.Float(), nullable=False),
        sa.Column('reason', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'adm_pricing_simulations',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=True),
        sa.Column('label', sa.String(150), nullable=True),
        sa.Column('tipo_cambio', sa.Float(), nullable=False),
        sa.Column('clientes', sa.Integer(), nullable=False),
        sa.Column('abono_usd', sa.Float(), nullable=False),
        sa.Column('green_api_usd', sa.Float(), nullable=False),
        sa.Column('openai_usd', sa.Float(), nullable=False),
        sa.Column('server_tramo1', sa.Float(), nullable=False),
        sa.Column('server_tramo2', sa.Float(), nullable=False),
        sa.Column('server_tramo3', sa.Float(), nullable=False),
        sa.Column('ganancia_ars', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('adm_pricing_simulations')
    op.drop_table('adm_client_pricing_history')
    op.drop_table('adm_client_pricing')
