"""Add openai_project_id, OpenAICreditReload history table and adm_system_config

Idempotente, mismo estilo que b3e7d1a4f6c2_add_openai_credit_alert.py.

Revision ID: c4d8f2b6a1e9
Revises: b3e7d1a4f6c2
Create Date: 2026-09-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'c4d8f2b6a1e9'
down_revision: Union[str, Sequence[str], None] = 'b3e7d1a4f6c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns(insp, table):
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _add_missing_columns(insp, table, columns):
    existing = _existing_columns(insp, table)
    for col in columns:
        if col.name not in existing:
            op.add_column(table, col)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = inspect(bind)

    _add_missing_columns(insp, 'adm_client_settings', [
        sa.Column('openai_project_id', sa.String(100), nullable=True),
    ])

    if 'adm_openai_credit_reloads' not in insp.get_table_names():
        op.create_table(
            'adm_openai_credit_reloads',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
            sa.Column('amount_usd', sa.Float(), nullable=False),
            sa.Column('receipt_file_path', sa.String(255), nullable=True),
            sa.Column('note', sa.String(255), nullable=True),
            sa.Column('created_by', sa.String(150), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    if 'adm_system_config' not in insp.get_table_names():
        op.create_table(
            'adm_system_config',
            sa.Column('key', sa.String(100), primary_key=True),
            sa.Column('value_encrypted', sa.Text(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    pass
