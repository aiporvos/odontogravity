"""un solo turno activo por profesional y horario

Revision ID: f1a2b3c4d5e6
Revises: a7b8c9d0e1f2
Create Date: 2026-08-19 02:00:00.000000

Ultima barrera contra la doble reserva. La validacion en codigo
(motivo_no_agendable) hace un check-then-insert, y entre el chequeo y el INSERT
hay una ventana en la que dos pacientes pueden ver el mismo hueco libre. Un
indice unico en la base cierra esa ventana: gana uno y el otro recibe un
IntegrityError que el servicio traduce en "ese horario acaba de ser tomado".

Es un indice PARCIAL: solo aplica a turnos vivos. Los cancelados y los borrados
logicamente no ocupan el horario, asi que se excluyen; si no, cancelar un turno
impediria volver a agendar en ese mismo hueco.

Si la base YA tiene duplicados, crear el indice fallaria y tumbaria el arranque
de una app en produccion. En ese caso la migracion NO crea el indice y deja el
detalle en el log, para que se limpien con scripts/detectar_turnos_duplicados.py
y se vuelva a desplegar.
"""
from typing import Sequence, Union
import logging

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

INDICE = "uq_turno_activo_por_profesional"

# Un turno "vivo" es el que efectivamente ocupa el sillon.
CONDICION = "is_deleted = false AND status NOT IN ('cancelled', 'no_show')"

DUPLICADOS = sa.text(f"""
    SELECT professional_id, start_time, COUNT(*) AS cuantos
    FROM appointments
    WHERE {CONDICION}
    GROUP BY professional_id, start_time
    HAVING COUNT(*) > 1
    ORDER BY cuantos DESC
""")


def _tiene_tabla(tabla: str) -> bool:
    return tabla in sa.inspect(op.get_bind()).get_table_names()


def _tiene_indice(tabla: str, indice: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if tabla not in inspector.get_table_names():
        return False
    return indice in {i["name"] for i in inspector.get_indexes(tabla)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _tiene_tabla("appointments") or _tiene_indice("appointments", INDICE):
        return

    # Los indices parciales son de PostgreSQL. En SQLite (tests) se crea uno
    # comun, que igual sirve como barrera para lo que se prueba.
    if bind.dialect.name != "postgresql":
        op.create_index(INDICE, "appointments", ["professional_id", "start_time"], unique=True)
        return

    duplicados = bind.execute(DUPLICADOS).fetchall()
    if duplicados:
        detalle = ", ".join(
            f"prof={d.professional_id} {d.start_time} x{d.cuantos}" for d in duplicados[:10]
        )
        logger.error(
            "No se creo el indice %s: la base ya tiene %d horario(s) con turnos "
            "duplicados. Limpialos con scripts/detectar_turnos_duplicados.py y "
            "volve a desplegar. Detalle: %s",
            INDICE, len(duplicados), detalle,
        )
        return

    op.execute(
        f"CREATE UNIQUE INDEX {INDICE} ON appointments (professional_id, start_time) "
        f"WHERE {CONDICION}"
    )


def downgrade() -> None:
    if _tiene_indice("appointments", INDICE):
        op.drop_index(INDICE, table_name="appointments")
