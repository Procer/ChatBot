"""Add granular scheduling settings

Revision ID: f2e5ea12b3d8
Revises: c8bbc341c599
Create Date: 2026-05-29 21:47:00.123456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2e5ea12b3d8'
down_revision: Union[str, Sequence[str], None] = 'c8bbc341c599'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('adm_client_settings', sa.Column('enable_working_hours_for_scheduling', sa.Boolean(), nullable=True, server_default=sa.text('0')))
    op.add_column('data_knowledge', sa.Column('scheduling_hours', sa.Text(), nullable=True))
    op.add_column('data_knowledge', sa.Column('appointment_duration', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('data_knowledge', 'appointment_duration')
    op.drop_column('data_knowledge', 'scheduling_hours')
    op.drop_column('adm_client_settings', 'enable_working_hours_for_scheduling')
