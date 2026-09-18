"""Agrega working_hours_json para el horario semanal estructurado (por día, turnos múltiples)

Reemplaza gradualmente el texto libre de 'working_hours' (parseado por regex, sin soporte real
para horarios distintos por día de la semana) - pedido real de un usuario (2026-09-17) para
poder cargar sábados con otro horario que los días de semana, y turnos separados mañana/tarde
sin ambigüedad. Columna nullable e idempotente: los clientes existentes siguen con el texto
libre hasta que guarden el nuevo editor (ver src/scheduling_hours.py).

Revision ID: a3c9f7e1b5d2
Revises: d7e1a9c3b5f2
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'a3c9f7e1b5d2'
down_revision: Union[str, Sequence[str], None] = 'd7e1a9c3b5f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    existing = {c["name"] for c in insp.get_columns('adm_client_settings')}
    if 'working_hours_json' not in existing:
        op.add_column('adm_client_settings', sa.Column('working_hours_json', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('adm_client_settings', 'working_hours_json')
