"""Médicos con usuario/contraseña para el verificador público de protocolos + sus eventos (ingresos / comprobaciones)

Revision ID: d5f9b2e7c3a1
Revises: c4e8a1d6b2f9
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'd5f9b2e7c3a1'
down_revision: Union[str, Sequence[str], None] = 'c4e8a1d6b2f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = set(inspect(op.get_bind()).get_table_names())
    if 'data_protocol_doctors' not in have:
        op.create_table(
            'data_protocol_doctors',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False, index=True),
            sa.Column('username', sa.String(60), nullable=False),
            sa.Column('name', sa.String(120), nullable=True),
            sa.Column('password_hash', sa.String(200), nullable=False),
            sa.Column('active', sa.Boolean(), nullable=True, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
    if 'data_protocol_doctor_events' not in have:
        op.create_table(
            'data_protocol_doctor_events',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('client_id', sa.Integer(), nullable=False, index=True),
            sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('data_protocol_doctors.id'), nullable=False, index=True),
            sa.Column('kind', sa.String(10), nullable=False),
            sa.Column('status', sa.String(10), nullable=True),
            sa.Column('at', sa.DateTime(), nullable=True, index=True),
        )


def downgrade() -> None:
    have = set(inspect(op.get_bind()).get_table_names())
    for t in ('data_protocol_doctor_events', 'data_protocol_doctors'):
        if t in have:
            op.drop_table(t)
