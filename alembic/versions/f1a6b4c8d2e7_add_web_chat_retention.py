"""Add web chat retention (dias sin actividad antes de borrar un chat web)

Revision ID: f1a6b4c8d2e7
Revises: e9f5a3b7c1d6
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'f1a6b4c8d2e7'
down_revision: Union[str, Sequence[str], None] = 'e9f5a3b7c1d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if 'adm_client_settings' in insp.get_table_names():
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        if 'web_chat_retention_days' not in cols:
            op.add_column('adm_client_settings', sa.Column('web_chat_retention_days', sa.Integer(), nullable=True, server_default='180'))


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if 'adm_client_settings' in insp.get_table_names():
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        if 'web_chat_retention_days' in cols:
            with op.batch_alter_table('adm_client_settings') as batch:
                batch.drop_column('web_chat_retention_days')
