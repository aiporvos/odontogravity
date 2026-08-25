"""un profesional no puede tener dos turnos que se pisen

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-08-25 15:00:00.000000

El indice unico que existia solo cubria (professional_id, start_time), o sea
horarios de inicio IDENTICOS. Un turno de 10:00 a 10:30 y otro que arranca a las
10:15 se pisan sin repetir el inicio, asi que pasaban limpio.

PostgreSQL resuelve esto con una restriccion EXCLUDE sobre rangos: dos filas del
mismo profesional no pueden tener rangos de tiempo que se superpongan. Es la
unica barrera real contra la doble reserva, porque no depende de que el codigo
haya validado bien: la base lo rechaza siempre.

Como el indice viejo, solo aplica a turnos vivos: los cancelados y los borrados
logicamente no ocupan el sillon.

Si la base ya tiene turnos superpuestos la restriccion no se puede crear. En ese
caso NO se aborta el arranque —hay pacientes esperando del otro lado— sino que
se avisa por log con el detalle, para limpiarlos con
scripts/detectar_turnos_duplicados.py y volver a desplegar.
"""
from typing import Sequence, Union
import logging

from alembic import op
import sqlalchemy as sa

revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

RESTRICCION = "no_solapar_turnos_por_profesional"
INDICE_VIEJO = "uq_turno_activo_por_profesional"

VIVO = "is_deleted = false AND status NOT IN ('cancelled', 'no_show')"

# make_interval es inmutable, que es lo que exige una restriccion de exclusion.
RANGO = ("tsrange(start_time, start_time + "
         "make_interval(mins => COALESCE(duration_minutes, 30)))")

SUPERPUESTOS = sa.text(f"""
    SELECT a.id, a.professional_id, a.start_time, b.start_time AS choca_con
    FROM appointments a
    JOIN appointments b
      ON a.professional_id = b.professional_id
     AND a.id < b.id
     AND {RANGO.replace('start_time', 'a.start_time').replace('duration_minutes', 'a.duration_minutes')}
      && {RANGO.replace('start_time', 'b.start_time').replace('duration_minutes', 'b.duration_minutes')}
    WHERE a.is_deleted = false AND a.status NOT IN ('cancelled', 'no_show')
      AND b.is_deleted = false AND b.status NOT IN ('cancelled', 'no_show')
    LIMIT 20
""")


def _existe(nombre: str) -> bool:
    return bool(op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": nombre}
    ).scalar())


def _existe_indice(nombre: str) -> bool:
    return bool(op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": nombre}
    ).scalar())


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return   # las restricciones de exclusion son de PostgreSQL
    if "appointments" not in sa.inspect(bind).get_table_names():
        return
    if _existe(RESTRICCION):
        return

    superpuestos = bind.execute(SUPERPUESTOS).fetchall()
    if superpuestos:
        detalle = ", ".join(
            f"prof={s.professional_id} {s.start_time} choca con {s.choca_con}"
            for s in superpuestos[:5]
        )
        logger.error(
            "No se creo la restriccion %s: la base ya tiene %d turno(s) "
            "superpuestos. Limpialos con scripts/detectar_turnos_duplicados.py "
            "y volve a desplegar. Detalle: %s",
            RESTRICCION, len(superpuestos), detalle,
        )
        return

    # Necesaria para combinar igualdad (uuid) con solapamiento (rango) en el
    # mismo indice GiST.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        f"ALTER TABLE appointments ADD CONSTRAINT {RESTRICCION} "
        f"EXCLUDE USING gist ("
        f"  professional_id WITH =, "
        f"  {RANGO} WITH &&"
        f") WHERE ({VIVO})"
    )

    # El indice viejo queda cubierto por la restriccion nueva: un horario
    # identico es un caso particular de solapamiento.
    if _existe_indice(INDICE_VIEJO):
        op.drop_index(INDICE_VIEJO, table_name="appointments")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    if _existe(RESTRICCION):
        op.execute(f"ALTER TABLE appointments DROP CONSTRAINT {RESTRICCION}")
    if not _existe_indice(INDICE_VIEJO):
        op.execute(
            f"CREATE UNIQUE INDEX {INDICE_VIEJO} ON appointments "
            f"(professional_id, start_time) WHERE ({VIVO})"
        )
