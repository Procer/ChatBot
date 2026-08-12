"""Add greeting question (offer a document segment on first message)

Revision ID: a9c3e1f6b2d7
Revises: b2e6f9a3c7d1
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a9c3e1f6b2d7'
down_revision: Union[str, Sequence[str], None] = 'b2e6f9a3c7d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'adm_client_settings',
        sa.Column('greeting_question_enabled', sa.Boolean(), nullable=True, server_default='0'),
    )
    op.add_column(
        'adm_client_settings',
        sa.Column('greeting_question_text', sa.Text(), nullable=True),
    )
    op.add_column(
        'adm_client_settings',
        sa.Column('greeting_question_segment_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_greeting_question_segment',
        'adm_client_settings', 'data_doc_segments',
        ['greeting_question_segment_id'], ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_greeting_question_segment', 'adm_client_settings', type_='foreignkey')
    op.drop_column('adm_client_settings', 'greeting_question_segment_id')
    op.drop_column('adm_client_settings', 'greeting_question_text')

    op.execute("""
        DECLARE @constraint_name NVARCHAR(200)
        SELECT @constraint_name = dc.name
        FROM sys.default_constraints dc
        JOIN sys.columns c ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
        WHERE dc.parent_object_id = OBJECT_ID('adm_client_settings') AND c.name = 'greeting_question_enabled'
        IF @constraint_name IS NOT NULL
            EXEC('ALTER TABLE adm_client_settings DROP CONSTRAINT ' + @constraint_name)
    """)
    op.drop_column('adm_client_settings', 'greeting_question_enabled')
