"""add professional_schedule table

Revision ID: e5f0a1b2c3d4
Revises: d4e9f3a7b8c5
Create Date: 2026-08-13 12:20:00.000000

Idempotente a proposito: la app crea el esquema con Base.metadata.create_all()
en cada arranque, asi que Alembic se encontraba con objetos ya creados y
abortaba con DuplicateColumn/DuplicateTable, cortando todo el encadenado.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'e5f0a1b2c3d4'
down_revision: Union[str, None] = 'd4e9f3a7b8c5'
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
    if _tiene_tabla('professional_schedule'):
        return
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
    if not _tiene_indice('professional_schedule', 'ix_professional_schedule_professional'):
        op.create_index('ix_professional_schedule_professional', 'professional_schedule', ['professional_id'])


def downgrade() -> None:
    op.drop_index('ix_professional_schedule_professional', table_name='professional_schedule')
    op.drop_table('professional_schedule')
