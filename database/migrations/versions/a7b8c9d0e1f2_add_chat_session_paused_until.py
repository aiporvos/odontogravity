"""add paused_until to chat_sessions

Revision ID: a7b8c9d0e1f2
Revises: e5f0a1b2c3d4
Create Date: 2026-08-18 20:10:00.000000

Idempotente a propósito. La cadena de migraciones de este proyecto viene
fallando justamente por no serlo: la app crea el esquema con
Base.metadata.create_all() en cada arranque, así que cuando Alembic intenta
agregar algo que create_all ya creó, aborta con DuplicateColumn y se corta
todo el encadenado. Esta migración chequea antes de tocar nada, para no sumar
un eslabón más al problema.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'e5f0a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tiene_columna(tabla: str, columna: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if tabla not in inspector.get_table_names():
        return False
    return columna in {c["name"] for c in inspector.get_columns(tabla)}


def upgrade() -> None:
    if not _tiene_columna("chat_sessions", "paused_until"):
        op.add_column("chat_sessions", sa.Column("paused_until", sa.DateTime(), nullable=True))


def downgrade() -> None:
    if _tiene_columna("chat_sessions", "paused_until"):
        op.drop_column("chat_sessions", "paused_until")
