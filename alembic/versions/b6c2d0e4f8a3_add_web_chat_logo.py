"""Add web_chat_logo (logo propio del chat web)

Revision ID: b6c2d0e4f8a3
Revises: a5b1c9d3e7f2
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'b6c2d0e4f8a3'
down_revision: Union[str, Sequence[str], None] = 'a5b1c9d3e7f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if 'adm_client_settings' in insp.get_table_names():
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        if 'web_chat_logo' not in cols:
            op.add_column('adm_client_settings', sa.Column('web_chat_logo', sa.String(255), nullable=True))


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if 'adm_client_settings' in insp.get_table_names():
        cols = {c['name'] for c in insp.get_columns('adm_client_settings')}
        if 'web_chat_logo' in cols:
            with op.batch_alter_table('adm_client_settings') as batch:
                batch.drop_column('web_chat_logo')
