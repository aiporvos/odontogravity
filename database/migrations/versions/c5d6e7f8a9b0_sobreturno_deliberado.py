"""recepcion puede cargar un sobreturno a proposito

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-09-04 15:00:00.000000

La restriccion a3b4c5d6e7f8 impide que dos turnos del mismo profesional se
pisen, y esta bien: es la barrera contra la doble reserva accidental, la que el
bot nunca puede saltear. Pero tambien bloqueaba el caso legitimo — recepcion que
encaja un paciente encima de un horario ya tomado porque asi funciona el
consultorio.

La diferencia entre los dos casos no es tecnica, es de intencion. Asi que ahora
se escribe: `is_overbooking` marca el turno que se cargo a proposito por encima
de otro. Las filas marcadas quedan FUERA del indice de la restriccion, que sigue
valiendo igual de fuerte para todas las demas.

Marcarlo importa mas que permitirlo. Antes el panel deducia cual era el
sobreturno mirando cual se habia creado despues, y esa marca se mudaba sola: si
se cancelaba el original, el sobreturno pasaba a ser el turno "normal" y nadie
se enteraba de que ese horario habia estado doblado.
"""
from typing import Sequence, Union

import logging

from alembic import op
import sqlalchemy as sa

logger = logging.getLogger("alembic.runtime.migration")

revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RESTRICCION = "no_solapar_turnos_por_profesional"

RANGO = ("tsrange(start_time, start_time + "
         "make_interval(mins => COALESCE(duration_minutes, 30)))")

# Igual que antes, mas la salvedad del sobreturno deliberado.
VIVO = ("is_deleted = false AND status NOT IN ('cancelled', 'no_show') "
        "AND is_overbooking = false")


SUPERPUESTOS = sa.text(f"""
    SELECT a.id, a.professional_id, a.start_time, b.start_time AS choca_con
    FROM appointments a
    JOIN appointments b
      ON a.professional_id = b.professional_id
     AND a.id < b.id
     AND tsrange(a.start_time, a.start_time + make_interval(mins => COALESCE(a.duration_minutes, 30)))
      && tsrange(b.start_time, b.start_time + make_interval(mins => COALESCE(b.duration_minutes, 30)))
    WHERE a.is_deleted = false AND a.status NOT IN ('cancelled', 'no_show') AND a.is_overbooking = false
      AND b.is_deleted = false AND b.status NOT IN ('cancelled', 'no_show') AND b.is_overbooking = false
    LIMIT 20
""")


def _tiene_columna(tabla: str, columna: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if tabla not in inspector.get_table_names():
        return False
    return any(c["name"] == columna for c in inspector.get_columns(tabla))


def _existe_restriccion(nombre: str) -> bool:
    return bool(op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": nombre}
    ).scalar())


def upgrade() -> None:
    bind = op.get_bind()
    if "appointments" not in sa.inspect(bind).get_table_names():
        return

    if not _tiene_columna("appointments", "is_overbooking"):
        op.add_column("appointments", sa.Column(
            "is_overbooking", sa.Boolean(), nullable=False, server_default=sa.false(),
        ))

    if bind.dialect.name != "postgresql":
        return   # las restricciones de exclusion son de PostgreSQL

    # Se mira ANTES de tocar nada. Si la base tiene superposiciones sin marcar,
    # la restriccion nueva no se puede crear; el punto es no dejarla caida por
    # intentarlo. Cuando la restriccion vieja ya existe no puede haber
    # superposiciones vivas —ella misma las impide—, asi que este chequeo solo
    # muerde cuando a3b4c5d6e7f8 no habia podido crearla.
    superpuestos = bind.execute(SUPERPUESTOS).fetchall()
    if superpuestos:
        detalle = ", ".join(
            f"prof={s.professional_id} {s.start_time} choca con {s.choca_con}"
            for s in superpuestos[:5]
        )
        logger.error(
            "La base tiene %d turno(s) superpuestos sin marcar como sobreturno: "
            "no se toca la restriccion %s. Limpialos con "
            "scripts/detectar_turnos_duplicados.py y volve a desplegar. "
            "Detalle: %s",
            len(superpuestos), RESTRICCION, detalle,
        )
        return

    if _existe_restriccion(RESTRICCION):
        op.execute(f"ALTER TABLE appointments DROP CONSTRAINT {RESTRICCION}")

    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        f"ALTER TABLE appointments ADD CONSTRAINT {RESTRICCION} "
        f"EXCLUDE USING gist ("
        f"  professional_id WITH =, "
        f"  {RANGO} WITH &&"
        f") WHERE ({VIVO})"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if _existe_restriccion(RESTRICCION):
        op.execute(f"ALTER TABLE appointments DROP CONSTRAINT {RESTRICCION}")
    # Volver a la version que no conoce el sobreturno exigiria borrar los que ya
    # existan: se deja la tabla sin la restriccion antes que perder turnos.
