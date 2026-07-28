"""Add followup content tables

Revision ID: babed82ae87f
Revises: e7c1b5a9d4f0
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'babed82ae87f'
down_revision: Union[str, Sequence[str], None] = 'e7c1b5a9d4f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'data_followup_content',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('message_text', sa.Text(), nullable=False),
        sa.Column('media_path', sa.String(255), nullable=True),
        sa.Column('interval_minutes', sa.Integer(), nullable=False, server_default='120'),
        sa.Column('valid_from', sa.String(20), nullable=False),
        sa.Column('valid_until', sa.String(20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'bot_followup_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
        sa.Column('thread_id', sa.String(100), nullable=False),
        sa.Column('content_id', sa.Integer(), sa.ForeignKey('data_followup_content.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('bot_followup_log')
    op.drop_table('data_followup_content')
