"""Add employee assignment to appointments

Revision ID: a9c3e7f21d4b
Revises: f1a2b3c4d5e6
Create Date: 2026-08-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9c3e7f21d4b'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'data_employees',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('adm_clients.id'), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('color', sa.String(length=7), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.add_column('data_appointments', sa.Column('employee_id', sa.Integer(), sa.ForeignKey('data_employees.id'), nullable=True))
    op.add_column('adm_client_settings', sa.Column('enable_employee_assignment', sa.Boolean(), nullable=True, server_default=sa.text('0')))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('adm_client_settings', 'enable_employee_assignment')
    op.drop_column('data_appointments', 'employee_id')
    op.drop_table('data_employees')
