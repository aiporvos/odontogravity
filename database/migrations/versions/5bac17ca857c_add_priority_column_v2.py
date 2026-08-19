"""add_priority_column_v2

Revision ID: 5bac17ca857c
Revises: 84b4817b0297
Create Date: 2026-07-08 12:01:33.752608

Idempotente a proposito: la app crea el esquema con Base.metadata.create_all()
en cada arranque, asi que Alembic se encontraba con objetos ya creados y
abortaba con DuplicateColumn/DuplicateTable, cortando todo el encadenado.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '5bac17ca857c'
down_revision: Union[str, None] = None
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
    if not _tiene_columna('odontogram_entries', 'priority'):
        op.add_column('odontogram_entries', sa.Column('priority', sa.String(length=20), nullable=True))


def downgrade() -> None:
    if _tiene_columna('odontogram_entries', 'priority'):
        op.drop_column('odontogram_entries', 'priority')
