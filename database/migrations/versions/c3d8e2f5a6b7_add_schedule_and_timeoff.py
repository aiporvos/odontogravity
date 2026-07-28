"""add clinic_schedule and professional_time_off

Revision ID: c3d8e2f5a6b7
Revises: b2f7c1a9d3e4
Create Date: 2026-07-28 10:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'c3d8e2f5a6b7'
down_revision: Union[str, None] = 'b2f7c1a9d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'clinic_schedule',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('weekday', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    op.create_table(
        'professional_time_off',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('professional_id', sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('professionals.id'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    op.create_index('ix_time_off_professional', 'professional_time_off', ['professional_id'])
    op.create_index('ix_time_off_date', 'professional_time_off', ['date'])

    # Seed con las reglas actuales (Lun-Vie 09:00-12:30 y 17:00-20:30; miércoles sin tarde)
    rows = []
    for wd in range(0, 5):  # 0=Lun ... 4=Vie
        rows.append(f"(gen_random_uuid(), {wd}, '09:00', '12:30', true, now())")
        if wd != 2:  # miércoles cerrado a la tarde
            rows.append(f"(gen_random_uuid(), {wd}, '17:00', '20:30', true, now())")
    op.execute(
        "INSERT INTO clinic_schedule (id, weekday, start_time, end_time, is_active, created_at) VALUES "
        + ", ".join(rows)
    )


def downgrade() -> None:
    op.drop_index('ix_time_off_date', table_name='professional_time_off')
    op.drop_index('ix_time_off_professional', table_name='professional_time_off')
    op.drop_table('professional_time_off')
    op.drop_table('clinic_schedule')
