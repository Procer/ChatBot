"""add custom reminder hours

Revision ID: bde26b796c05
Revises: f2e5ea12b3d8
Create Date: 2026-06-01 22:19:56.943057

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bde26b796c05'
down_revision: Union[str, Sequence[str], None] = 'f2e5ea12b3d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('adm_client_settings', sa.Column('reminder_24h_hours', sa.Integer(), nullable=True, server_default=sa.text('24')))
    op.add_column('adm_client_settings', sa.Column('reminder_2h_hours', sa.Integer(), nullable=True, server_default=sa.text('2')))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('adm_client_settings', 'reminder_2h_hours')
    op.drop_column('adm_client_settings', 'reminder_24h_hours')
