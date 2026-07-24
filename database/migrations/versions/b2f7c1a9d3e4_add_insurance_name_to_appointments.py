"""add_insurance_name_to_appointments

Revision ID: b2f7c1a9d3e4
Revises: 5bac17ca857c
Create Date: 2026-07-24 10:30:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'b2f7c1a9d3e4'
down_revision: Union[str, None] = '5bac17ca857c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('appointments', sa.Column('insurance_name', sa.String(length=200), nullable=True))
    # Backfill: para los turnos ya existentes, copiar la obra social de la
    # ficha del paciente. Subconsulta correlacionada (portable Postgres/SQLite).
    op.execute(
        """
        UPDATE appointments
        SET insurance_name = (
            SELECT p.insurance_name FROM patients p WHERE p.id = appointments.patient_id
        )
        WHERE insurance_name IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column('appointments', 'insurance_name')
