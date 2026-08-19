"""add clinic_holidays table

Revision ID: d4e9f3a7b8c5
Revises: c3d8e2f5a6b7
Create Date: 2026-08-10 19:30:00.000000

Idempotente a proposito: la app crea el esquema con Base.metadata.create_all()
en cada arranque, asi que Alembic se encontraba con objetos ya creados y
abortaba con DuplicateColumn/DuplicateTable, cortando todo el encadenado.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd4e9f3a7b8c5'
down_revision: Union[str, None] = 'c3d8e2f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tiene_tabla(tabla: str) -> bool:
    return tabla in sa.inspect(op.get_bind()).get_table_names()


def _tiene_columna(tabla: str, columna: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if tabla not in inspector.get_table_names():
        return False
    return columna in {c["name"] for c in inspector.get_columns(tabla)}


def _tiene_indice(tabla: str, indice: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if tabla not in inspector.get_table_names():
        return False
    return indice in {i["name"] for i in inspector.get_indexes(tabla)}


def upgrade() -> None:
    if _tiene_tabla('clinic_holidays'):
        return
    op.create_table(
        'clinic_holidays',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('date', sa.Date(), nullable=False, unique=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    if not _tiene_indice('clinic_holidays', 'ix_clinic_holidays_date'):
        op.create_index('ix_clinic_holidays_date', 'clinic_holidays', ['date'])


def downgrade() -> None:
    op.drop_index('ix_clinic_holidays_date', table_name='clinic_holidays')
    op.drop_table('clinic_holidays')
