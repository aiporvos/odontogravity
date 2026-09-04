"""el telefono deja de ser obligatorio: solo nombre y apellido lo son

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-04 10:30:00.000000

Recepcion carga fichas desde la agenda de papel, donde la mayoria de los turnos
no tiene telefono anotado. Con la columna NOT NULL, la unica forma de guardar
esa ficha era inventar un numero — y un telefono inventado es peor que ninguno:
el recordatorio le llega a un tercero.

Queda como el DNI (ver f2a3b4c5d6e7): la ficha existe con nombre y apellido, y
el dato se completa cuando el paciente llega. Sin telefono no hay recordatorio,
y eso ahora se avisa en el log en vez de fallar tres veces en silencio.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _telefono_es_obligatorio() -> bool:
    inspector = sa.inspect(op.get_bind())
    if "patients" not in inspector.get_table_names():
        return False
    for col in inspector.get_columns("patients"):
        if col["name"] == "phone":
            return not col["nullable"]
    return False


def upgrade() -> None:
    if _telefono_es_obligatorio():
        op.alter_column("patients", "phone", existing_type=sa.String(30), nullable=True)

    # Los "TMP-xxxx" los invento el propio panel cuando el DNI era obligatorio:
    # no son el documento de nadie, y en la lista de pacientes se leen como si
    # lo fueran. Ahora que la columna admite NULL, se limpian.
    inspector = sa.inspect(op.get_bind())
    if "patients" in inspector.get_table_names():
        op.execute("UPDATE patients SET dni = NULL WHERE dni LIKE 'TMP-%'")


def downgrade() -> None:
    # Volver atras exigiria inventar un telefono para las fichas que no lo
    # tienen, que es exactamente lo que esta migracion vino a evitar.
    pass
