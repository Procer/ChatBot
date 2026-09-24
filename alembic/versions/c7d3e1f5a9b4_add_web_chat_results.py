"""Add web chat results (vinculacion DNI+protocolo y PDFs dentro del chat)

Columnas web_chat_results_enabled / web_chat_consent en adm_client_settings y tablas
web_links, web_deliveries y web_link_attempts. Idempotente.

Revision ID: c7d3e1f5a9b4
Revises: b6c2d0e4f8a3
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'c7d3e1f5a9b4'
down_revision: Union[str, Sequence[str], None] = 'b6c2d0e4f8a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ('web_chat_results_enabled', lambda: sa.Column('web_chat_results_enabled', sa.Boolean(), nullable=True, server_default=sa.text('0'))),
    ('web_chat_consent', lambda: sa.Column('web_chat_consent', sa.Text(), nullable=True)),
]


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = insp.get_table_names()
    if 'adm_client_settings' in tables:
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        for name, make in _COLUMNS:
            if name not in cols:
                op.add_column('adm_client_settings', make())
    if 'web_links' not in tables:
        op.create_table(
            'web_links',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
            sa.Column('device_id', sa.Integer(), sa.ForeignKey('web_devices.id'), nullable=False),
            sa.Column('dni', sa.String(12), nullable=False),
            sa.Column('name', sa.String(60), nullable=True),
            sa.Column('protocol', sa.String(20), nullable=False),
            sa.Column('status', sa.String(12), nullable=False),
            sa.Column('consent_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('verified_at', sa.DateTime(), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.Column('last_check_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_web_links_client_id', 'web_links', ['client_id'])
        op.create_index('ix_web_links_device_id', 'web_links', ['device_id'])
    if 'web_deliveries' not in tables:
        op.create_table(
            'web_deliveries',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
            sa.Column('device_id', sa.Integer(), sa.ForeignKey('web_devices.id'), nullable=False),
            sa.Column('link_id', sa.Integer(), sa.ForeignKey('web_links.id'), nullable=False),
            sa.Column('file_id', sa.String(100), nullable=False),
            sa.Column('protocol', sa.String(20), nullable=True),
            sa.Column('event_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_web_deliveries_device_id', 'web_deliveries', ['device_id'])
        op.create_index('ix_web_deliveries_event_id', 'web_deliveries', ['event_id'])
        # Un mismo archivo no se entrega dos veces al mismo celular
        op.create_index('ux_web_deliveries_device_file', 'web_deliveries', ['device_id', 'file_id'], unique=True)
    if 'web_link_attempts' not in tables:
        op.create_table(
            'web_link_attempts',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
            sa.Column('device_id', sa.Integer(), nullable=True),
            sa.Column('ip', sa.String(64), nullable=True),
            sa.Column('dni', sa.String(12), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_web_link_attempts_created_at', 'web_link_attempts', ['created_at'])


def downgrade() -> None:
    insp = inspect(op.get_bind())
    tables = insp.get_table_names()
    for t in ('web_link_attempts', 'web_deliveries', 'web_links'):
        if t in tables:
            op.drop_table(t)
    if 'adm_client_settings' in tables:
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        with op.batch_alter_table('adm_client_settings') as batch:
            for name, _ in _COLUMNS:
                if name in cols:
                    batch.drop_column(name)
