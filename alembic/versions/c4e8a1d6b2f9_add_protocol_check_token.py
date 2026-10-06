"""Link público del verificador de protocolos para médicos (adm_client_settings.protocol_check_token)

Revision ID: c4e8a1d6b2f9
Revises: b7d2f4a9c1e6
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'c4e8a1d6b2f9'
down_revision: Union[str, Sequence[str], None] = 'b7d2f4a9c1e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = {c['name'] for c in inspect(op.get_bind()).get_columns('adm_client_settings')}
    if 'protocol_check_token' not in have:
        op.add_column('adm_client_settings', sa.Column('protocol_check_token', sa.String(64), nullable=True))


def downgrade() -> None:
    have = {c['name'] for c in inspect(op.get_bind()).get_columns('adm_client_settings')}
    if 'protocol_check_token' in have:
        with op.batch_alter_table('adm_client_settings') as batch:
            batch.drop_column('protocol_check_token')
