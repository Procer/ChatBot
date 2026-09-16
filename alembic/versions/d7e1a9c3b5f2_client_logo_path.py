"""Add logo_path to adm_client_settings

Idempotente, mismo estilo que c4d8f2b6a1e9_openai_credit_reload_history.py.

Revision ID: d7e1a9c3b5f2
Revises: c4d8f2b6a1e9
Create Date: 2026-09-15 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'd7e1a9c3b5f2'
down_revision: Union[str, Sequence[str], None] = 'c4d8f2b6a1e9'
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
        sa.Column('logo_path', sa.String(255), nullable=True),
    ])


def downgrade() -> None:
    """Downgrade schema."""
    pass
