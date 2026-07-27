"""Add Google Drive sync columns to ClientSettings and Document

Revision ID: 9d3f5a1c8e2b
Revises: 32c3e30d47f8
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9d3f5a1c8e2b'
down_revision: Union[str, Sequence[str], None] = '32c3e30d47f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('adm_client_settings', sa.Column('gdrive_refresh_token_encrypted', sa.Text(), nullable=True))
    op.add_column('adm_client_settings', sa.Column('gdrive_connected_email', sa.String(255), nullable=True))
    op.add_column('adm_client_settings', sa.Column('gdrive_connected_at', sa.DateTime(), nullable=True))
    op.add_column('adm_client_settings', sa.Column('gdrive_root_folder_id', sa.String(255), nullable=True))
    op.add_column('adm_client_settings', sa.Column('gdrive_root_folder_name', sa.String(255), nullable=True))
    op.add_column('adm_client_settings', sa.Column('gdrive_last_sync_at', sa.DateTime(), nullable=True))
    op.add_column('adm_client_settings', sa.Column('gdrive_last_sync_summary', sa.Text(), nullable=True))
    op.add_column('adm_client_settings', sa.Column('gdrive_needs_reconnect', sa.Boolean(), nullable=True, server_default=sa.false()))

    op.add_column('data_doc_documents', sa.Column('external_file_id', sa.String(255), nullable=True))
    op.add_column('data_doc_documents', sa.Column('gdrive_last_seen_at', sa.DateTime(), nullable=True))
    op.create_index('ix_data_doc_documents_client_external', 'data_doc_documents', ['client_id', 'external_file_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_data_doc_documents_client_external', table_name='data_doc_documents')
    op.drop_column('data_doc_documents', 'gdrive_last_seen_at')
    op.drop_column('data_doc_documents', 'external_file_id')

    op.drop_column('adm_client_settings', 'gdrive_needs_reconnect')
    op.drop_column('adm_client_settings', 'gdrive_last_sync_summary')
    op.drop_column('adm_client_settings', 'gdrive_last_sync_at')
    op.drop_column('adm_client_settings', 'gdrive_root_folder_name')
    op.drop_column('adm_client_settings', 'gdrive_root_folder_id')
    op.drop_column('adm_client_settings', 'gdrive_connected_at')
    op.drop_column('adm_client_settings', 'gdrive_connected_email')
    op.drop_column('adm_client_settings', 'gdrive_refresh_token_encrypted')
