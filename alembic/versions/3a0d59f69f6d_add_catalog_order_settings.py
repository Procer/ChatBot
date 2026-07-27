"""Add catalog order settings

Revision ID: 3a0d59f69f6d
Revises: 6b5aeb668281
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3a0d59f69f6d'
down_revision: Union[str, Sequence[str], None] = '6b5aeb668281'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('adm_client_settings', sa.Column('catalog_order_fields', sa.Text(), nullable=True))
    op.add_column('adm_client_settings', sa.Column('catalog_min_lead_days', sa.Integer(), nullable=True))
    op.add_column('adm_client_settings', sa.Column('catalog_confirm_attributes', sa.Boolean(), nullable=True))
    op.add_column('adm_client_settings', sa.Column('catalog_include_images', sa.Boolean(), nullable=True))
    op.add_column('adm_client_settings', sa.Column('catalog_response_style', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('adm_client_settings', 'catalog_response_style')
    op.drop_column('adm_client_settings', 'catalog_include_images')
    op.drop_column('adm_client_settings', 'catalog_confirm_attributes')
    op.drop_column('adm_client_settings', 'catalog_min_lead_days')
    op.drop_column('adm_client_settings', 'catalog_order_fields')
