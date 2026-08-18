"""Add openai_api_key_encrypted to adm_client_settings

Revision ID: d4f7b2c9a1e5
Revises: c3f8a5d2e6b1
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4f7b2c9a1e5'
down_revision: Union[str, Sequence[str], None] = 'c3f8a5d2e6b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'adm_client_settings',
        sa.Column('openai_api_key_encrypted', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('adm_client_settings', 'openai_api_key_encrypted')
