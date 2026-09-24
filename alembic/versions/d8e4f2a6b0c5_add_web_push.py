"""Add web push (notificaciones del chat web) y vigia de Drive

Columnas web_push_public_key / web_push_private_key_encrypted / web_chat_watch_at en
adm_client_settings y tabla web_push_subs. Idempotente.

Revision ID: d8e4f2a6b0c5
Revises: c7d3e1f5a9b4
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'd8e4f2a6b0c5'
down_revision: Union[str, Sequence[str], None] = 'c7d3e1f5a9b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ('web_push_public_key', lambda: sa.Column('web_push_public_key', sa.String(120), nullable=True)),
    ('web_push_private_key_encrypted', lambda: sa.Column('web_push_private_key_encrypted', sa.Text(), nullable=True)),
    ('web_chat_watch_at', lambda: sa.Column('web_chat_watch_at', sa.DateTime(), nullable=True)),
]


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = insp.get_table_names()
    if 'adm_client_settings' in tables:
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        for name, make in _COLUMNS:
            if name not in cols:
                op.add_column('adm_client_settings', make())
    if 'web_push_subs' not in tables:
        op.create_table(
            'web_push_subs',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
            sa.Column('device_id', sa.Integer(), sa.ForeignKey('web_devices.id'), nullable=False),
            sa.Column('endpoint', sa.Text(), nullable=False),
            sa.Column('endpoint_hash', sa.String(64), nullable=False),
            sa.Column('p256dh', sa.String(200), nullable=False),
            sa.Column('auth', sa.String(100), nullable=False),
            sa.Column('topic_alerts', sa.Boolean(), nullable=True, server_default=sa.text('1')),
            sa.Column('topic_news', sa.Boolean(), nullable=True, server_default=sa.text('0')),
            sa.Column('fail_count', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('last_ok_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_web_push_subs_client_id', 'web_push_subs', ['client_id'])
        op.create_index('ix_web_push_subs_device_id', 'web_push_subs', ['device_id'])
        op.create_index('ux_web_push_subs_endpoint_hash', 'web_push_subs', ['endpoint_hash'], unique=True)


def downgrade() -> None:
    insp = inspect(op.get_bind())
    tables = insp.get_table_names()
    if 'web_push_subs' in tables:
        op.drop_table('web_push_subs')
    if 'adm_client_settings' in tables:
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        with op.batch_alter_table('adm_client_settings') as batch:
            for name, _ in _COLUMNS:
                if name in cols:
                    batch.drop_column(name)
