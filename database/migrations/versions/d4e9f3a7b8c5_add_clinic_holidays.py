"""add clinic_holidays table

Revision ID: d4e9f3a7b8c5
Revises: c3d8e2f5a6b7
Create Date: 2026-08-10 19:30:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd4e9f3a7b8c5'
down_revision: Union[str, None] = 'c3d8e2f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'clinic_holidays',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('date', sa.Date(), nullable=False, unique=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    op.create_index('ix_clinic_holidays_date', 'clinic_holidays', ['date'])


def downgrade() -> None:
    op.drop_index('ix_clinic_holidays_date', table_name='clinic_holidays')
    op.drop_table('clinic_holidays')
