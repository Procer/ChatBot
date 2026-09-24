"""Add web chat (chat web propio): settings y tablas web_devices / web_events

Columnas web_chat_* + feat_web_chat en adm_client_settings y tablas web_devices y web_events. Idempotente.

Revision ID: a5b1c9d3e7f2
Revises: d6f2b9e4a8c1
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'a5b1c9d3e7f2'
down_revision: Union[str, Sequence[str], None] = 'd6f2b9e4a8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ('feat_web_chat', lambda: sa.Column('feat_web_chat', sa.Boolean(), nullable=True, server_default=sa.text('0'))),
    ('web_chat_enabled', lambda: sa.Column('web_chat_enabled', sa.Boolean(), nullable=True, server_default=sa.text('0'))),
    ('web_chat_title', lambda: sa.Column('web_chat_title', sa.String(100), nullable=True)),
    ('web_chat_subtitle', lambda: sa.Column('web_chat_subtitle', sa.String(100), nullable=True)),
    ('web_chat_welcome', lambda: sa.Column('web_chat_welcome', sa.Text(), nullable=True)),
    ('web_chat_color', lambda: sa.Column('web_chat_color', sa.String(9), nullable=True)),
    ('web_chat_buttons', lambda: sa.Column('web_chat_buttons', sa.Text(), nullable=True)),
    ('web_chat_daily_cap', lambda: sa.Column('web_chat_daily_cap', sa.Integer(), nullable=True, server_default='30')),
    ('web_chat_global_daily_cap', lambda: sa.Column('web_chat_global_daily_cap', sa.Integer(), nullable=True, server_default='1000')),
]


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = insp.get_table_names()
    if 'adm_client_settings' in tables:
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        for name, make in _COLUMNS:
            if name not in cols:
                op.add_column('adm_client_settings', make())
    if 'web_devices' not in tables:
        op.create_table(
            'web_devices',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
            sa.Column('public_id', sa.String(32), nullable=False, unique=True),
            sa.Column('token_hash', sa.String(64), nullable=False),
            sa.Column('user_agent', sa.String(255), nullable=True),
            sa.Column('blocked', sa.Boolean(), nullable=True, server_default=sa.text('0')),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_web_devices_client_id', 'web_devices', ['client_id'])
        op.create_index('ix_web_devices_token_hash', 'web_devices', ['token_hash'])
    if 'web_events' not in tables:
        op.create_table(
            'web_events',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
            sa.Column('device_id', sa.Integer(), sa.ForeignKey('web_devices.id'), nullable=False),
            sa.Column('kind', sa.String(12), nullable=False),
            sa.Column('text', sa.Text(), nullable=True),
            sa.Column('attach_json', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_web_events_device_id', 'web_events', ['device_id'])


def downgrade() -> None:
    insp = inspect(op.get_bind())
    tables = insp.get_table_names()
    if 'web_events' in tables:
        op.drop_table('web_events')
    if 'web_devices' in tables:
        op.drop_table('web_devices')
    if 'adm_client_settings' in tables:
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        with op.batch_alter_table('adm_client_settings') as batch:
            for name, _ in _COLUMNS:
                if name in cols:
                    batch.drop_column(name)
