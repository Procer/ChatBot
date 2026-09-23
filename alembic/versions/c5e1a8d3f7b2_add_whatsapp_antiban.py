"""Add WhatsApp anti-ban settings and follow-up opt-out table

Columnas wa_* en adm_client_settings (pausa humana, tope por minuto, tope de proactivos,
leyenda de baja) y tabla bot_followup_optout. Idempotente.

Revision ID: c5e1a8d3f7b2
Revises: b7d2e9c4a1f3
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'c5e1a8d3f7b2'
down_revision: Union[str, Sequence[str], None] = 'b7d2e9c4a1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ('wa_humanize_enabled', lambda: sa.Column('wa_humanize_enabled', sa.Boolean(), nullable=True, server_default=sa.text('1'))),
    ('wa_typing_indicator', lambda: sa.Column('wa_typing_indicator', sa.Boolean(), nullable=True, server_default=sa.text('1'))),
    ('wa_delay_min_seconds', lambda: sa.Column('wa_delay_min_seconds', sa.Integer(), nullable=True, server_default='2')),
    ('wa_delay_max_seconds', lambda: sa.Column('wa_delay_max_seconds', sa.Integer(), nullable=True, server_default='5')),
    ('wa_rate_per_minute', lambda: sa.Column('wa_rate_per_minute', sa.Integer(), nullable=True, server_default='20')),
    ('wa_proactive_per_hour', lambda: sa.Column('wa_proactive_per_hour', sa.Integer(), nullable=True, server_default='40')),
    ('wa_optout_enabled', lambda: sa.Column('wa_optout_enabled', sa.Boolean(), nullable=True, server_default=sa.text('0'))),
    ('wa_optout_footer', lambda: sa.Column('wa_optout_footer', sa.Text(), nullable=True)),
]


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = insp.get_table_names()
    if 'adm_client_settings' in tables:
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        for name, make in _COLUMNS:
            if name not in cols:
                op.add_column('adm_client_settings', make())
    if 'bot_followup_optout' not in tables:
        op.create_table(
            'bot_followup_optout',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
            sa.Column('thread_id', sa.String(100), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if 'bot_followup_optout' in insp.get_table_names():
        op.drop_table('bot_followup_optout')
    if 'adm_client_settings' in insp.get_table_names():
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        with op.batch_alter_table('adm_client_settings') as batch:
            for name, _ in _COLUMNS:
                if name in cols:
                    batch.drop_column(name)
