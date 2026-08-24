"""lapida: paused_until (revision revertida que produccion ya tenia aplicada)

Revision ID: f6a1b2c3d4e5
Revises: e5f0a1b2c3d4
Create Date: 2026-08-13 15:40:00.000000

Esta revision existio de verdad: la creo fe7caa8 ("que el personal pueda pausar
al bot") y el revert 33559ca borro el archivo. Pero para entonces produccion ya
la habia aplicado y tenia 'f6a1b2c3d4e5' anotado en alembic_version.

Borrar el archivo no borra ese registro. Desde ese revert, cada arranque en
produccion moria con:

    CommandError: Can't locate revision identified by 'f6a1b2c3d4e5'

y nadie se entero, porque el upgrade estaba envuelto en un try/except que solo
logueaba. Recien se hizo visible cuando el arranque paso a cortar ante un fallo
de migracion.

Por eso vuelve el archivo, como lapida: no aporta nada nuevo (la columna la crea
igual a7b8c9d0e1f2, que ahora cuelga de esta), pero le devuelve a Alembic el
eslabon que le falta para poder avanzar desde donde quedo produccion.

Moraleja: una migracion aplicada en produccion no se revierte borrando el
archivo. Se revierte con una migracion nueva que la deshaga.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a1b2c3d4e5'
down_revision: Union[str, None] = 'e5f0a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tiene_columna(tabla: str, columna: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if tabla not in inspector.get_table_names():
        return False
    return columna in {c["name"] for c in inspector.get_columns(tabla)}


def upgrade() -> None:
    # Idempotente: en produccion la columna ya existe y esto no hace nada; en
    # una base nueva la crea, igual que haria a7b8c9d0e1f2 a continuacion.
    if not _tiene_columna("chat_sessions", "paused_until"):
        op.add_column("chat_sessions", sa.Column("paused_until", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # No se baja aca: la columna se sigue usando y quien la elimine deberia ser
    # a7b8c9d0e1f2, que es la revision viva de este cambio.
    pass
