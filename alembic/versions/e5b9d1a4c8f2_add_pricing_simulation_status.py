"""Add status tracking to pricing simulations (borrador/enviada/aprobada/rechazada)

Revision ID: e5b9d1a4c8f2
Revises: d8a3c5f2b7e1
Create Date: 2026-07-31 00:00:02.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5b9d1a4c8f2'
down_revision: Union[str, Sequence[str], None] = 'd8a3c5f2b7e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('adm_pricing_simulations', sa.Column('status', sa.String(20), nullable=False, server_default='borrador'))
    op.add_column('adm_pricing_simulations', sa.Column('status_updated_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('adm_pricing_simulations', 'status_updated_at')
    op.drop_column('adm_pricing_simulations', 'status')
