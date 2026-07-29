"""Add per-segment search trigger phrases and search fields

Revision ID: a4d8e2f6c1b9
Revises: f3a7c1e9b2d4
Create Date: 2026-07-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a4d8e2f6c1b9'
down_revision: Union[str, Sequence[str], None] = 'f3a7c1e9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('data_doc_segments', sa.Column('search_trigger_phrases', sa.Text(), nullable=True))
    op.add_column('data_doc_segments', sa.Column('search_fields', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('data_doc_segments', 'search_fields')
    op.drop_column('data_doc_segments', 'search_trigger_phrases')
