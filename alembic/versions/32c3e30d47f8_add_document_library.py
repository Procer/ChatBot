"""Add document library (segments, documents, users, sessions, search logs)

Revision ID: 32c3e30d47f8
Revises: f2a9c31e7b4d
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '32c3e30d47f8'
down_revision: Union[str, Sequence[str], None] = 'f2a9c31e7b4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('adm_client_settings', sa.Column('feat_document_library', sa.Boolean(), nullable=True, server_default=sa.false()))
    op.add_column('adm_client_settings', sa.Column('doc_library_trigger_phrases', sa.Text(), nullable=True))

    op.create_table(
        'data_doc_segments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('is_public', sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column('auth_mode', sa.String(20), nullable=True, server_default='generic'),
        sa.Column('generic_password_hash', sa.String(255), nullable=True),
        sa.Column('session_expiry_days', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'data_doc_library_users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
        sa.Column('username', sa.String(100), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'data_doc_library_user_segments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
        sa.Column('library_user_id', sa.Integer(), sa.ForeignKey('data_doc_library_users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('segment_id', sa.Integer(), sa.ForeignKey('data_doc_segments.id', ondelete='CASCADE'), nullable=False),
    )

    op.create_table(
        'data_doc_documents',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('keywords', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('file_path', sa.String(255), nullable=True),
        sa.Column('source_type', sa.String(20), nullable=True, server_default='local'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'data_doc_document_segments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('data_doc_documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('segment_id', sa.Integer(), sa.ForeignKey('data_doc_segments.id', ondelete='CASCADE'), nullable=False),
    )

    op.create_table(
        'data_doc_sessions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
        sa.Column('thread_id', sa.String(100), nullable=False),
        sa.Column('segment_id', sa.Integer(), sa.ForeignKey('data_doc_segments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('library_user_id', sa.Integer(), sa.ForeignKey('data_doc_library_users.id'), nullable=True),
        sa.Column('authenticated_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'data_doc_search_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
        sa.Column('thread_id', sa.String(100), nullable=False),
        sa.Column('query', sa.String(255), nullable=False),
        sa.Column('found', sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column('results_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('document_title', sa.String(255), nullable=True),
        sa.Column('auth_blocked', sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('data_doc_search_logs')
    op.drop_table('data_doc_sessions')
    op.drop_table('data_doc_document_segments')
    op.drop_table('data_doc_documents')
    op.drop_table('data_doc_library_user_segments')
    op.drop_table('data_doc_library_users')
    op.drop_table('data_doc_segments')
    op.drop_column('adm_client_settings', 'doc_library_trigger_phrases')
    op.drop_column('adm_client_settings', 'feat_document_library')
