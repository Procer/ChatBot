"""Replace Google Drive OAuth columns with per-client service account key

Revision ID: f3a7c1e9b2d4
Revises: babed82ae87f
Create Date: 2026-07-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f3a7c1e9b2d4'
down_revision: Union[str, Sequence[str], None] = 'babed82ae87f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('adm_client_settings', sa.Column('gdrive_service_account_json_encrypted', sa.Text(), nullable=True))
    op.add_column('adm_client_settings', sa.Column('gdrive_service_account_email', sa.String(255), nullable=True))
    op.add_column('adm_client_settings', sa.Column('gdrive_share_revoked', sa.Boolean(), nullable=True, server_default=sa.false()))

    op.drop_column('adm_client_settings', 'google_oauth_client_secret_encrypted')
    op.drop_column('adm_client_settings', 'google_oauth_client_id')

    # SQL Server nombra el default constraint automáticamente (no con el nombre de la columna):
    # hay que encontrarlo y borrarlo antes de poder dropear la columna.
    op.execute("""
        DECLARE @constraint_name NVARCHAR(200)
        SELECT @constraint_name = dc.name
        FROM sys.default_constraints dc
        JOIN sys.columns c ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
        WHERE dc.parent_object_id = OBJECT_ID('adm_client_settings') AND c.name = 'gdrive_needs_reconnect'
        IF @constraint_name IS NOT NULL
            EXEC('ALTER TABLE adm_client_settings DROP CONSTRAINT ' + @constraint_name)
    """)
    op.drop_column('adm_client_settings', 'gdrive_needs_reconnect')
    op.drop_column('adm_client_settings', 'gdrive_connected_at')
    op.drop_column('adm_client_settings', 'gdrive_connected_email')
    op.drop_column('adm_client_settings', 'gdrive_refresh_token_encrypted')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('adm_client_settings', sa.Column('gdrive_refresh_token_encrypted', sa.Text(), nullable=True))
    op.add_column('adm_client_settings', sa.Column('gdrive_connected_email', sa.String(255), nullable=True))
    op.add_column('adm_client_settings', sa.Column('gdrive_connected_at', sa.DateTime(), nullable=True))
    op.add_column('adm_client_settings', sa.Column('gdrive_needs_reconnect', sa.Boolean(), nullable=True, server_default=sa.false()))
    op.add_column('adm_client_settings', sa.Column('google_oauth_client_id', sa.String(255), nullable=True))
    op.add_column('adm_client_settings', sa.Column('google_oauth_client_secret_encrypted', sa.Text(), nullable=True))

    op.execute("""
        DECLARE @constraint_name NVARCHAR(200)
        SELECT @constraint_name = dc.name
        FROM sys.default_constraints dc
        JOIN sys.columns c ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
        WHERE dc.parent_object_id = OBJECT_ID('adm_client_settings') AND c.name = 'gdrive_share_revoked'
        IF @constraint_name IS NOT NULL
            EXEC('ALTER TABLE adm_client_settings DROP CONSTRAINT ' + @constraint_name)
    """)
    op.drop_column('adm_client_settings', 'gdrive_share_revoked')
    op.drop_column('adm_client_settings', 'gdrive_service_account_email')
    op.drop_column('adm_client_settings', 'gdrive_service_account_json_encrypted')
