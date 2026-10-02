"""Interruptor por canal: el bot responde en WhatsApp / Telegram / chat web (adm_client_settings.bot_reply_*)

Revision ID: b7d2f4a9c1e6
Revises: a3c9e5b1d7f4
Create Date: 2026-10-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'b7d2f4a9c1e6'
down_revision: Union[str, Sequence[str], None] = 'a3c9e5b1d7f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLS = ('bot_reply_whatsapp', 'bot_reply_telegram', 'bot_reply_web')


def upgrade() -> None:
    insp = inspect(op.get_bind())
    have = {c['name'] for c in insp.get_columns('adm_client_settings')}
    for name in COLS:
        if name not in have:
            op.add_column('adm_client_settings', sa.Column(name, sa.Boolean(), nullable=True, server_default='1'))
            # SQL Server no rellena las filas existentes al agregar una columna nullable con default
            op.execute(sa.text(f'UPDATE adm_client_settings SET {name} = 1 WHERE {name} IS NULL'))


def downgrade() -> None:
    insp = inspect(op.get_bind())
    have = {c['name'] for c in insp.get_columns('adm_client_settings')}
    for name in COLS:
        if name in have:
            with op.batch_alter_table('adm_client_settings') as batch:
                batch.drop_column(name)
