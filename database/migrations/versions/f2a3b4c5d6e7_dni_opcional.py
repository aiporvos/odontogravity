"""el DNI deja de ser obligatorio para dar de alta un paciente

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-25 12:00:00.000000

Pedirle el DNI al paciente por WhatsApp era el mayor punto de abandono del alta:

    bot:      Necesito tu nombre, apellido y DNI. ¿Me los podés pasar?
    paciente: Maria Prueba
    bot:      Necesito tu DNI para crear tu ficha. ¿Me lo podés pasar?
    paciente: 101010
    bot:      El DNI que me diste parece tener 6 dígitos...

Tres mensajes mas para un dato que el sistema no necesita para reservar: al
paciente lo identifica su numero de WhatsApp, que ademas es mas confiable que un
DNI (Meta verifica el numero; un DNI lo sabe cualquiera).

El DNI sigue haciendo falta para facturarle a la obra social, pero eso lo
completa recepcion cuando el paciente llega, con el documento en la mano y sin
errores de tipeo.

En PostgreSQL un indice UNIQUE admite varios NULL, asi que las fichas sin DNI
conviven sin chocar entre si.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _dni_es_obligatorio() -> bool:
    inspector = sa.inspect(op.get_bind())
    if "patients" not in inspector.get_table_names():
        return False
    for col in inspector.get_columns("patients"):
        if col["name"] == "dni":
            return not col["nullable"]
    return False


def upgrade() -> None:
    if _dni_es_obligatorio():
        op.alter_column("patients", "dni", existing_type=sa.String(20), nullable=True)


def downgrade() -> None:
    # Volver atras exigiria inventar un DNI para las fichas que no lo tienen, y
    # un DNI inventado es peor que ninguno: se deja como esta.
    pass
