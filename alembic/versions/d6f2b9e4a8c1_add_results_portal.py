"""Add results portal ("Mis Resultados") settings and search log table

Columnas results_portal_* en adm_client_settings y tabla data_results_search_logs. Idempotente.

Revision ID: d6f2b9e4a8c1
Revises: c5e1a8d3f7b2
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'd6f2b9e4a8c1'
down_revision: Union[str, Sequence[str], None] = 'c5e1a8d3f7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    ('results_portal_enabled', lambda: sa.Column('results_portal_enabled', sa.Boolean(), nullable=True, server_default=sa.text('0'))),
    ('results_portal_folder_id', lambda: sa.Column('results_portal_folder_id', sa.String(255), nullable=True)),
    ('results_portal_folder_name', lambda: sa.Column('results_portal_folder_name', sa.String(255), nullable=True)),
    ('results_portal_days', lambda: sa.Column('results_portal_days', sa.Integer(), nullable=True, server_default='30')),
    ('results_portal_phone', lambda: sa.Column('results_portal_phone', sa.String(50), nullable=True)),
    ('results_portal_welcome', lambda: sa.Column('results_portal_welcome', sa.Text(), nullable=True)),
]


def upgrade() -> None:
    insp = inspect(op.get_bind())
    tables = insp.get_table_names()
    if 'adm_client_settings' in tables:
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        for name, make in _COLUMNS:
            if name not in cols:
                op.add_column('adm_client_settings', make())
    if 'data_results_search_logs' not in tables:
        op.create_table(
            'data_results_search_logs',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
            sa.Column('dni', sa.String(20), nullable=False),
            sa.Column('ip', sa.String(64), nullable=True),
            sa.Column('results_count', sa.Integer(), nullable=True),
            sa.Column('error', sa.Boolean(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if 'data_results_search_logs' in insp.get_table_names():
        op.drop_table('data_results_search_logs')
    if 'adm_client_settings' in insp.get_table_names():
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        with op.batch_alter_table('adm_client_settings') as batch:
            for name, _ in _COLUMNS:
                if name in cols:
                    batch.drop_column(name)
