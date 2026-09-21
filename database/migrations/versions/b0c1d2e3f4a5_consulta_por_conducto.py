"""consulta por conducto (30') vs tratamiento de conducto (60')

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-09-21 00:30:00.000000

Pedido del consultorio: si piden conducto hay que preguntar si viene derivado
y si es consulta de evaluacion (30 min) o ya realizar el tratamiento (1 h).
Antes un solo tipo "Conducto" de 60' hacia que el bot agendara siempre una hora.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOMBRE = "Consulta por conducto"
SINONIMOS = [
    "consulta por conducto",
    "consulta conducto",
    "evaluacion conducto",
    "evaluación conducto",
    "conducto derivado",
    "derivado conducto",
]


def upgrade() -> None:
    bind = op.get_bind()
    if "tipos_consulta" not in sa.inspect(bind).get_table_names():
        return
    if bind.execute(
        sa.text("SELECT 1 FROM tipos_consulta WHERE lower(nombre) = lower(:n)"),
        {"n": NOMBRE},
    ).scalar():
        return

    import uuid as _uuid
    from datetime import datetime as _dt

    ahora = _dt.utcnow()
    tabla = sa.table(
        "tipos_consulta",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("nombre", sa.String),
        sa.column("duracion_minutos", sa.Integer),
        sa.column("especialidad", sa.String),
        sa.column("sinonimos", postgresql.ARRAY(sa.String())),
        sa.column("is_active", sa.Boolean),
        sa.column("is_deleted", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(tabla, [{
        "id": _uuid.uuid4(),
        "nombre": NOMBRE,
        "duracion_minutos": 30,
        "especialidad": "Endodoncia",
        "sinonimos": SINONIMOS,
        "is_active": True,
        "is_deleted": False,
        "created_at": ahora,
        "updated_at": ahora,
    }])


def downgrade() -> None:
    bind = op.get_bind()
    if "tipos_consulta" not in sa.inspect(bind).get_table_names():
        return
    bind.execute(
        sa.text("DELETE FROM tipos_consulta WHERE lower(nombre) = lower(:n)"),
        {"n": NOMBRE},
    )
