"""Add per-topic scheduling_days to data_knowledge

Revision ID: b7d4e2a1f9c3
Revises: a9c3e1f6b2d7
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7d4e2a1f9c3'
down_revision: Union[str, Sequence[str], None] = 'a9c3e1f6b2d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'data_knowledge',
        sa.Column('scheduling_days', sa.String(50), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('data_knowledge', 'scheduling_days')
