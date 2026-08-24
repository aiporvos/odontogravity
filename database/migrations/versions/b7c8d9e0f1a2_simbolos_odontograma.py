"""simbolos nuevos del odontograma (sff, fracture, bridge)

Revision ID: b7c8d9e0f1a2
Revises: f1a2b3c4d5e6
Create Date: 2026-08-19 02:10:00.000000

PostgreSQL no actualiza solo los valores de un ENUM cuando cambia el modelo, y
Base.metadata.create_all() tampoco los agrega si el tipo ya existe. Esto vivia
como un ALTER TYPE suelto en el lifespan de main.py, ejecutandose en cada
arranque dentro de un try/except que se tragaba cualquier error. Va aca, que es
donde se registran los cambios de esquema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SIMBOLOS_NUEVOS = ["sff", "fracture", "bridge"]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # en SQLite los Enum son VARCHAR con CHECK, no hay tipo que ampliar

    existe = bind.execute(sa.text(
        "SELECT 1 FROM pg_type WHERE typname = 'toothsymbol'"
    )).scalar()
    if not existe:
        return  # la tabla todavia no se creo; create_all lo hara con el enum completo

    for simbolo in SIMBOLOS_NUEVOS:
        op.execute(f"ALTER TYPE toothsymbol ADD VALUE IF NOT EXISTS '{simbolo}'")


def downgrade() -> None:
    # PostgreSQL no permite quitar valores de un ENUM sin recrear el tipo, y
    # hacerlo borraria datos existentes. Se deja intencionalmente vacio.
    pass
