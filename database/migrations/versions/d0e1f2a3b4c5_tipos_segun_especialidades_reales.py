"""alinear los tipos de consulta con las especialidades reales del consultorio

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-24 13:00:00.000000

Los tipos sembrados salieron del codigo viejo, no de lo que la clinica tiene
cargado. Cruzandolos con las especialidades reales aparecieron tres huecos:

  Elena  -> Ortodoncia, Odontopediatría, Tratamiento de conducto, Endodoncia,
            Limpieza, Arreglos
  Martin -> Cirugía, Implantes, Prótesis, Extracción, Limpieza, Arreglos

1. ODONTOPEDIATRÍA no existia como tipo, y es de Elena. Ya paso en produccion:
   una madre saco turno para Brunella y Julian —dos chicos— y los dos quedaron
   con Martin.
2. CIRUGÍA tampoco, y es de Martin.
3. CONTROL apuntaba a la especialidad "Consulta", que no tiene nadie, asi que
   caia en el fallback "cualquiera de los dos". Se deja sin especialidad, que
   es lo correcto y explicito para un motivo generico.

Solo toca lo que sigue igual a como se sembro: si la clinica ya lo edito desde
el panel, se respeta.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NUEVOS = [
    ("Odontopediatría", 30, "Odontopediatría",
     ["niño", "nino", "nena", "nene", "chico", "chica", "hijo", "hija",
      "pediatria", "odontopediatria", "criatura", "bebe", "menor"]),
    ("Cirugía", 60, "Cirugía",
     ["cirugia", "operacion", "operar", "operarme", "quirurgico"]),
]


def _tabla():
    return sa.table(
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


def upgrade() -> None:
    bind = op.get_bind()
    if "tipos_consulta" not in sa.inspect(bind).get_table_names():
        return

    import uuid as _uuid
    from datetime import datetime as _dt
    ahora = _dt.utcnow()

    faltantes = [
        {"id": _uuid.uuid4(), "nombre": n, "duracion_minutos": d,
         "especialidad": e, "sinonimos": s, "is_active": True,
         "is_deleted": False, "created_at": ahora, "updated_at": ahora}
        for n, d, e, s in NUEVOS
        if not bind.execute(
            sa.text("SELECT 1 FROM tipos_consulta WHERE lower(nombre) = lower(:n)"),
            {"n": n},
        ).scalar()
    ]
    if faltantes:
        op.bulk_insert(_tabla(), faltantes)

    # "Consulta" no es especialidad de nadie: un control lo puede atender
    # cualquiera, y decirlo con NULL es mas honesto que apuntar a algo que no
    # existe. Solo si sigue como se sembro.
    bind.execute(sa.text(
        "UPDATE tipos_consulta SET especialidad = NULL "
        "WHERE nombre = 'Control' AND especialidad = 'Consulta'"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if "tipos_consulta" not in sa.inspect(bind).get_table_names():
        return
    bind.execute(sa.text(
        "DELETE FROM tipos_consulta WHERE nombre IN ('Odontopediatría', 'Cirugía')"
    ))
    bind.execute(sa.text(
        "UPDATE tipos_consulta SET especialidad = 'Consulta' "
        "WHERE nombre = 'Control' AND especialidad IS NULL"
    ))
