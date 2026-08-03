"""Add per-client Google Drive sync interval

Revision ID: b2e6f9a3c7d1
Revises: e5b9d1a4c8f2
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2e6f9a3c7d1'
down_revision: Union[str, Sequence[str], None] = 'e5b9d1a4c8f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'adm_client_settings',
        sa.Column('gdrive_sync_interval_minutes', sa.Integer(), nullable=False, server_default='480'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
        DECLARE @constraint_name NVARCHAR(200)
        SELECT @constraint_name = dc.name
        FROM sys.default_constraints dc
        JOIN sys.columns c ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
        WHERE dc.parent_object_id = OBJECT_ID('adm_client_settings') AND c.name = 'gdrive_sync_interval_minutes'
        IF @constraint_name IS NOT NULL
            EXEC('ALTER TABLE adm_client_settings DROP CONSTRAINT ' + @constraint_name)
    """)
    op.drop_column('adm_client_settings', 'gdrive_sync_interval_minutes')
