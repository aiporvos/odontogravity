"""add professional_schedule table

Revision ID: e5f0a1b2c3d4
Revises: d4e9f3a7b8c5
Create Date: 2026-08-13 12:20:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'e5f0a1b2c3d4'
down_revision: Union[str, None] = 'd4e9f3a7b8c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'professional_schedule',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('professional_id', sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('professionals.id'), nullable=False),
        sa.Column('weekday', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    op.create_index('ix_professional_schedule_professional', 'professional_schedule', ['professional_id'])


def downgrade() -> None:
    op.drop_index('ix_professional_schedule_professional', table_name='professional_schedule')
    op.drop_table('professional_schedule')
