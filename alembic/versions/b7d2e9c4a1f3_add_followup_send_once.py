"""Add send_once to data_followup_content

Permite que una pieza de seguimiento se envie una sola vez por cliente (avisos urgentes)
en vez de reenviarse en cada periodo de inactividad. Idempotente.

Revision ID: b7d2e9c4a1f3
Revises: a3c9f7e1b5d2
Create Date: 2026-09-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'b7d2e9c4a1f3'
down_revision: Union[str, Sequence[str], None] = 'a3c9f7e1b5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if 'data_followup_content' not in insp.get_table_names():
        return
    cols = {c['name'] for c in insp.get_columns('data_followup_content')}
    if 'send_once' not in cols:
        op.add_column('data_followup_content', sa.Column('send_once', sa.Boolean(), nullable=True, server_default=sa.text('0')))


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if 'data_followup_content' in insp.get_table_names():
        cols = {c['name'] for c in insp.get_columns('data_followup_content')}
        if 'send_once' in cols:
            with op.batch_alter_table('data_followup_content') as batch:
                batch.drop_column('send_once')
