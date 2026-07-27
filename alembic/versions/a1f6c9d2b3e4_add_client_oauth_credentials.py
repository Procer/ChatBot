"""Add per-client Google OAuth app credentials to ClientSettings

Revision ID: a1f6c9d2b3e4
Revises: 9d3f5a1c8e2b
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1f6c9d2b3e4'
down_revision: Union[str, Sequence[str], None] = '9d3f5a1c8e2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('adm_client_settings', sa.Column('google_oauth_client_id', sa.String(255), nullable=True))
    op.add_column('adm_client_settings', sa.Column('google_oauth_client_secret_encrypted', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('adm_client_settings', 'google_oauth_client_secret_encrypted')
    op.drop_column('adm_client_settings', 'google_oauth_client_id')
