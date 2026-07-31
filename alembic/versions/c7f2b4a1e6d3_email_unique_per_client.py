"""Make adm_users.email unique per client instead of globally unique

Revision ID: c7f2b4a1e6d3
Revises: a4d8e2f6c1b9
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7f2b4a1e6d3'
down_revision: Union[str, Sequence[str], None] = 'a4d8e2f6c1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # El UNIQUE original de 'email' se creó sin nombre explícito (sa.UniqueConstraint('email')
    # dentro de create_table en 0f23147c3831), así que SQL Server le asignó un nombre de
    # sistema autogenerado. Hay que buscarlo dinámicamente para poder dropearlo.
    op.execute("""
        DECLARE @constraint_name NVARCHAR(200);
        SELECT @constraint_name = kc.name
        FROM sys.key_constraints kc
        JOIN sys.tables t ON kc.parent_object_id = t.object_id
        WHERE t.name = 'adm_users' AND kc.type = 'UQ';
        IF @constraint_name IS NOT NULL
            EXEC('ALTER TABLE adm_users DROP CONSTRAINT ' + @constraint_name);
    """)
    op.create_index('uq_adm_users_client_email', 'adm_users', ['client_id', 'email'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_adm_users_client_email', table_name='adm_users')
    op.create_unique_constraint('uq_adm_users_email', 'adm_users', ['email'])
