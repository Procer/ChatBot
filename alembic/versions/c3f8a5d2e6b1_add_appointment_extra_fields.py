"""Add appointment_extra_fields to data_knowledge

Revision ID: c3f8a5d2e6b1
Revises: b7d4e2a1f9c3
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3f8a5d2e6b1'
down_revision: Union[str, Sequence[str], None] = 'b7d4e2a1f9c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'data_knowledge',
        sa.Column('appointment_extra_fields', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('data_knowledge', 'appointment_extra_fields')
