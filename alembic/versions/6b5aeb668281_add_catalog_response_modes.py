"""Add catalog response modes

Revision ID: 6b5aeb668281
Revises: b78122fa21db
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '6b5aeb668281'
down_revision: Union[str, Sequence[str], None] = 'b78122fa21db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('adm_client_settings', sa.Column('catalog_require_lead_before_price', sa.Boolean(), nullable=True))
    op.add_column('adm_client_settings', sa.Column('catalog_lead_fields', sa.Text(), nullable=True))
    op.add_column('adm_client_settings', sa.Column('catalog_send_pdf_quote', sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('adm_client_settings', 'catalog_send_pdf_quote')
    op.drop_column('adm_client_settings', 'catalog_lead_fields')
    op.drop_column('adm_client_settings', 'catalog_require_lead_before_price')
