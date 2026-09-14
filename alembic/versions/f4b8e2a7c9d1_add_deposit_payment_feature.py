"""Add deposit payment (seña con Mercado Pago) feature

Nuevas columnas en adm_client_settings (config de Mercado Pago por cliente, mismo
aislamiento por tenant que openai_api_key_encrypted/gdrive_service_account_json_encrypted)
y en data_knowledge (monto de seña por servicio), más la tabla nueva
data_appointment_payments. Idempotente: chequea con el inspector antes de crear, mismo
estilo que e7c1b5a9d4f0_backfill_missing_columns.py.

Revision ID: f4b8e2a7c9d1
Revises: a9c3e7f21d4b
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'f4b8e2a7c9d1'
down_revision: Union[str, Sequence[str], None] = 'a9c3e7f21d4b'
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
    existing_tables = set(insp.get_table_names())

    _add_missing_columns(insp, 'adm_client_settings', [
        sa.Column('feat_deposit_payment', sa.Boolean(), nullable=True, server_default=sa.text('0')),
        sa.Column('mp_access_token_encrypted', sa.Text(), nullable=True),
        sa.Column('mp_public_key', sa.String(255), nullable=True),
        sa.Column('deposit_currency', sa.String(10), nullable=True, server_default='ARS'),
        sa.Column('deposit_payment_timeout_minutes', sa.Integer(), nullable=True, server_default=sa.text('30')),
        sa.Column('deposit_confirmed_template', sa.Text(), nullable=True),
        sa.Column('deposit_expired_template', sa.Text(), nullable=True),
    ])

    _add_missing_columns(insp, 'data_knowledge', [
        sa.Column('deposit_amount', sa.Float(), nullable=True),
    ])

    if 'data_appointment_payments' not in existing_tables:
        op.create_table(
            'data_appointment_payments',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('client_id', sa.Integer(), nullable=False),
            sa.Column('appointment_id', sa.Integer(), nullable=False),
            sa.Column('mp_preference_id', sa.String(100), nullable=True),
            sa.Column('mp_payment_id', sa.String(100), nullable=True),
            sa.Column('status', sa.String(30), nullable=True, server_default='pending'),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('currency', sa.String(10), nullable=True, server_default='ARS'),
            sa.Column('init_point', sa.String(500), nullable=True),
            sa.Column('raw_last_webhook', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('getutcdate()')),
            sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.text('getutcdate()')),
            sa.ForeignKeyConstraint(['client_id'], ['adm_clients.id']),
            sa.ForeignKeyConstraint(['appointment_id'], ['data_appointments.id']),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade() -> None:
    """Downgrade schema."""
    # No-op deliberado, mismo criterio que e7c1b5a9d4f0: revertir a mano si hace falta.
    pass
