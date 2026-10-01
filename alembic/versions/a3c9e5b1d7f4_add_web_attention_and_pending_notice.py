"""Chat web: atención (bot_alerts.thread_id) y aviso temprano de vínculo pendiente (web_links.pending_notice_at)

Revision ID: a3c9e5b1d7f4
Revises: f1a6b4c8d2e7
Create Date: 2026-10-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'a3c9e5b1d7f4'
down_revision: Union[str, Sequence[str], None] = 'f1a6b4c8d2e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(insp, table):
    return {c['name'] for c in insp.get_columns(table)} if table in insp.get_table_names() else None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    cols = _cols(insp, 'bot_alerts')
    if cols is not None and 'thread_id' not in cols:
        op.add_column('bot_alerts', sa.Column('thread_id', sa.String(100), nullable=True))
    cols = _cols(insp, 'web_links')
    if cols is not None and 'pending_notice_at' not in cols:
        op.add_column('web_links', sa.Column('pending_notice_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    insp = inspect(op.get_bind())
    cols = _cols(insp, 'bot_alerts')
    if cols is not None and 'thread_id' in cols:
        with op.batch_alter_table('bot_alerts') as batch:
            batch.drop_column('thread_id')
    cols = _cols(insp, 'web_links')
    if cols is not None and 'pending_notice_at' in cols:
        with op.batch_alter_table('web_links') as batch:
            batch.drop_column('pending_notice_at')
