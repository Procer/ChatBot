"""Backfill columns/tables that existed in models.py but were never created by any migration

Estas columnas/tablas quedaron huérfanas de migración: existían en bases de datos viejas
(creadas a mano o vía Base.metadata.create_all() antes de que Alembic las empezara a trackear),
así que ningún autogenerate las detectó como "nuevas". En una base 100% nueva (ej. un VPS
recién levantado) faltan por completo. Esta migración es idempotente: chequea con el inspector
de SQLAlchemy antes de crear cada tabla/columna, así no rompe bases que ya las tienen.

Revision ID: e7c1b5a9d4f0
Revises: a1f6c9d2b3e4
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'e7c1b5a9d4f0'
down_revision: Union[str, Sequence[str], None] = 'a1f6c9d2b3e4'
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
        sa.Column('company_address', sa.String(255), nullable=True),
        sa.Column('company_phone', sa.String(50), nullable=True),
        sa.Column('bot_name', sa.String(100), nullable=True),
        sa.Column('bot_tone', sa.String(50), nullable=True),
        sa.Column('out_of_office_enabled', sa.Boolean(), nullable=True, server_default=sa.text('0')),
        sa.Column('welcome_message_enabled', sa.Boolean(), nullable=True, server_default=sa.text('0')),
        sa.Column('welcome_threshold_days', sa.Integer(), nullable=True, server_default=sa.text('7')),
        sa.Column('test_mode_enabled', sa.Boolean(), nullable=True, server_default=sa.text('0')),
        sa.Column('test_numbers', sa.String(255), nullable=True),
        sa.Column('webhook_base_url', sa.String(255), nullable=True),
        sa.Column('whatsapp_enabled', sa.Boolean(), nullable=True, server_default=sa.text('1')),
        sa.Column('telegram_enabled', sa.Boolean(), nullable=True, server_default=sa.text('0')),
        sa.Column('telegram_token', sa.String(255), nullable=True),
        sa.Column('scheduling_provider', sa.String(50), nullable=True, server_default='local'),
        sa.Column('scheduling_days', sa.String(255), nullable=True, server_default='mon,tue,wed,thu,fri'),
        sa.Column('scheduling_capacity', sa.Integer(), nullable=True, server_default=sa.text('1')),
        sa.Column('appointment_duration', sa.Integer(), nullable=True, server_default=sa.text('30')),
        sa.Column('google_calendar_id', sa.String(255), nullable=True, server_default='primary'),
        sa.Column('reminder_24h_enabled', sa.Boolean(), nullable=True, server_default=sa.text('0')),
        sa.Column('reminder_24h_template', sa.Text(), nullable=True),
        sa.Column('reminder_2h_enabled', sa.Boolean(), nullable=True, server_default=sa.text('0')),
        sa.Column('reminder_2h_template', sa.Text(), nullable=True),
    ])

    _add_missing_columns(insp, 'data_knowledge', [
        sa.Column('scheduling_capacity', sa.Integer(), nullable=True, server_default=sa.text('1')),
        sa.Column('analyze_rag', sa.Boolean(), nullable=True, server_default=sa.text('1')),
        sa.Column('send_as_file', sa.Boolean(), nullable=True, server_default=sa.text('1')),
        sa.Column('required_role', sa.String(50), nullable=False, server_default='General'),
        sa.Column('tags_to_apply', sa.String(512), nullable=True),
    ])

    _add_missing_columns(insp, 'bot_user_profiles', [
        sa.Column('role', sa.String(50), nullable=False, server_default='General'),
    ])

    if 'data_scheduling_exceptions' not in existing_tables:
        op.create_table(
            'data_scheduling_exceptions',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('client_id', sa.Integer(), nullable=False),
            sa.Column('date', sa.String(20), nullable=False),
            sa.Column('start_time', sa.String(20), nullable=True),
            sa.Column('end_time', sa.String(20), nullable=True),
            sa.Column('description', sa.String(255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('getutcdate()')),
            sa.ForeignKeyConstraint(['client_id'], ['adm_clients.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if 'bot_tags' not in existing_tables:
        op.create_table(
            'bot_tags',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('client_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('color', sa.String(10), nullable=False, server_default='#6B7280'),
            sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.text('0')),
            sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('getutcdate()')),
            sa.ForeignKeyConstraint(['client_id'], ['adm_clients.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if 'bot_user_tags' not in existing_tables:
        op.create_table(
            'bot_user_tags',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('client_id', sa.Integer(), nullable=False),
            sa.Column('thread_id', sa.String(100), nullable=False),
            sa.Column('tag_id', sa.Integer(), nullable=False),
            sa.Column('assigned_at', sa.DateTime(), nullable=True, server_default=sa.text('getutcdate()')),
            sa.Column('assigned_by', sa.String(100), nullable=False, server_default='system'),
            sa.ForeignKeyConstraint(['client_id'], ['adm_clients.id']),
            sa.ForeignKeyConstraint(['tag_id'], ['bot_tags.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade() -> None:
    """Downgrade schema."""
    # No-op deliberado: esta migración es un backfill idempotente sobre estado histórico
    # inconsistente entre entornos; un downgrade automático podría borrar columnas que en
    # algunos entornos existían desde antes de Alembic. Revertir a mano si hace falta.
    pass
