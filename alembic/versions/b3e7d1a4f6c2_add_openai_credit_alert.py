"""Add OpenAI credit alert tracking to adm_client_settings

Idempotente, mismo estilo que e7c1b5a9d4f0_backfill_missing_columns.py.

Revision ID: b3e7d1a4f6c2
Revises: f4b8e2a7c9d1
Create Date: 2026-09-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'b3e7d1a4f6c2'
down_revision: Union[str, Sequence[str], None] = 'f4b8e2a7c9d1'
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
        sa.Column('openai_credit_loaded_usd', sa.Float(), nullable=True),
        sa.Column('openai_credit_loaded_at', sa.DateTime(), nullable=True),
        sa.Column('openai_alert_threshold_usd', sa.Float(), nullable=True, server_default=sa.text('3.0')),
        sa.Column('openai_alert_sent_at', sa.DateTime(), nullable=True),
    ])


def downgrade() -> None:
    """Downgrade schema."""
    pass
