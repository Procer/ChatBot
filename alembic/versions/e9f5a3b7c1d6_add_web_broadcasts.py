"""Add web broadcasts (avisos masivos del chat web)

Columnas web_chat_broadcast_* en adm_client_settings y tablas web_broadcasts y
web_broadcast_recipients. Idempotente.

Revision ID: e9f5a3b7c1d6
Revises: d8e4f2a6b0c5
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'e9f5a3b7c1d6'
down_revision: Union[str, Sequence[str], None] = 'd8e4f2a6b0c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ('web_chat_broadcast_cap', lambda: sa.Column('web_chat_broadcast_cap', sa.Integer(), nullable=True, server_default='3')),
    ('web_chat_broadcast_from', lambda: sa.Column('web_chat_broadcast_from', sa.Integer(), nullable=True, server_default='9')),
    ('web_chat_broadcast_to', lambda: sa.Column('web_chat_broadcast_to', sa.Integer(), nullable=True, server_default='20')),
]


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = insp.get_table_names()
    if 'adm_client_settings' in tables:
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        for name, make in _COLUMNS:
            if name not in cols:
                op.add_column('adm_client_settings', make())
    if 'web_broadcasts' not in tables:
        op.create_table(
            'web_broadcasts',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
            sa.Column('title', sa.String(80), nullable=False),
            sa.Column('body', sa.String(200), nullable=False),
            sa.Column('chat_message', sa.Text(), nullable=True),
            sa.Column('audience', sa.String(12), nullable=False),
            sa.Column('audience_days', sa.Integer(), nullable=True),
            sa.Column('status', sa.String(12), nullable=False),
            sa.Column('scheduled_at', sa.DateTime(), nullable=False),
            sa.Column('sent_at', sa.DateTime(), nullable=True),
            sa.Column('recipients', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('sent', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('failed', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('created_by', sa.String(150), nullable=True),
        )
        op.create_index('ix_web_broadcasts_client_id', 'web_broadcasts', ['client_id'])
    if 'web_broadcast_recipients' not in tables:
        op.create_table(
            'web_broadcast_recipients',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('broadcast_id', sa.Integer(), sa.ForeignKey('web_broadcasts.id'), nullable=False),
            sa.Column('device_id', sa.Integer(), sa.ForeignKey('web_devices.id'), nullable=False),
            sa.Column('ok', sa.Boolean(), nullable=True, server_default=sa.text('0')),
            sa.Column('clicked_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_web_broadcast_recipients_broadcast_id', 'web_broadcast_recipients', ['broadcast_id'])


def downgrade() -> None:
    insp = inspect(op.get_bind())
    tables = insp.get_table_names()
    for t in ('web_broadcast_recipients', 'web_broadcasts'):
        if t in tables:
            op.drop_table(t)
    if 'adm_client_settings' in tables:
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        with op.batch_alter_table('adm_client_settings') as batch:
            for name, _ in _COLUMNS:
                if name in cols:
                    batch.drop_column(name)
