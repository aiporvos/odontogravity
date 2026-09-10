"""marcar los solapamientos historicos y crear por fin la barrera de la base

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-09-09 21:45:00.000000

La restriccion EXCLUDE contra turnos superpuestos NUNCA se pudo crear en
produccion. Las migraciones a3b4c5d6e7f8 y c5d6e7f8a9b0 la intentan, detectan
que la base ya tiene solapamientos previos, avisan por log y se saltean. El
resultado: alembic figura en head y la agenda no tiene ninguna proteccion a
nivel base. Solo valida el codigo de la aplicacion.

Que son esos solapamientos, medido sobre una copia restaurada de produccion:

    89 pares sin marcar, CERO a futuro, todos entre el 27/07 y el 04/09
    154 turnos involucrados

Vienen de la carga de la agenda de papel: el cuaderno tiene bloques por hora con
dos pacientes debajo de cada uno, y se cargaron los dos con la misma hora en vez
de :00 y :30. Los 7 pares que si son futuros ya estan marcados como sobreturno
deliberado, cargados desde el panel.

Asi que se marcan los historicos como lo que fueron —dos pacientes en el mismo
horario— y con eso la restriccion entra. No se les cambia la hora: son turnos
que ya ocurrieron, corregirlos ahora seria inventar una historia que no paso.

De aca en adelante, la base rechaza cualquier superposicion que no sea un
sobreturno autorizado desde el panel.
"""
from typing import Sequence, Union
import logging

from alembic import op
import sqlalchemy as sa

revision: str = 'f8a9b0c1d2e3'
down_revision: Union[str, None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

RESTRICCION = "no_solapar_turnos_por_profesional"

RANGO = ("tsrange(start_time, start_time + "
         "make_interval(mins => COALESCE(duration_minutes, 30)))")

VIVO = ("is_deleted = false AND status NOT IN ('cancelled', 'no_show') "
        "AND is_overbooking = false")

# El mas nuevo del par es el que se cargo encima: ese es el sobreturno. Se
# repite porque marcar uno puede dejar otro par ya resuelto, y porque hay
# cadenas de tres turnos encimados.
MARCAR_UNO = sa.text(f"""
    UPDATE appointments SET is_overbooking = true
    WHERE id IN (
        SELECT CASE WHEN a.created_at >= b.created_at THEN a.id ELSE b.id END
        FROM appointments a
        JOIN appointments b
          ON a.professional_id = b.professional_id AND a.id < b.id
         AND tsrange(a.start_time, a.start_time + make_interval(mins => COALESCE(a.duration_minutes, 30)))
          && tsrange(b.start_time, b.start_time + make_interval(mins => COALESCE(b.duration_minutes, 30)))
        WHERE a.is_deleted = false AND b.is_deleted = false
          AND a.status NOT IN ('cancelled', 'no_show')
          AND b.status NOT IN ('cancelled', 'no_show')
          AND a.is_overbooking = false AND b.is_overbooking = false
        LIMIT 200
    )
""")

CUENTA_SIN_MARCAR = sa.text(f"""
    SELECT count(*) FROM appointments a
    JOIN appointments b ON a.professional_id = b.professional_id AND a.id < b.id
     AND tsrange(a.start_time, a.start_time + make_interval(mins => COALESCE(a.duration_minutes, 30)))
      && tsrange(b.start_time, b.start_time + make_interval(mins => COALESCE(b.duration_minutes, 30)))
    WHERE a.is_deleted = false AND b.is_deleted = false
      AND a.status NOT IN ('cancelled', 'no_show')
      AND b.status NOT IN ('cancelled', 'no_show')
      AND a.is_overbooking = false AND b.is_overbooking = false
""")


def _existe(bind, nombre: str) -> bool:
    return bool(bind.execute(
        sa.text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": nombre}
    ).scalar())


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return   # las restricciones de exclusion son de PostgreSQL
    if "appointments" not in sa.inspect(bind).get_table_names():
        return

    antes = bind.execute(CUENTA_SIN_MARCAR).scalar()
    logger.info("Solapamientos sin marcar antes de empezar: %s", antes)

    # Vueltas acotadas: cada una resuelve al menos un par, y si no baja se corta
    # en vez de girar para siempre.
    quedan = antes
    for _ in range(20):
        if not quedan:
            break
        bind.execute(MARCAR_UNO)
        nuevos = bind.execute(CUENTA_SIN_MARCAR).scalar()
        if nuevos >= quedan:
            break
        quedan = nuevos

    logger.info("Solapamientos sin marcar despues: %s", quedan)

    if quedan:
        logger.error(
            "No se pudo crear %s: quedan %s solapamientos sin marcar. "
            "Revisalos con scripts/detectar_turnos_duplicados.py.",
            RESTRICCION, quedan,
        )
        return

    if _existe(bind, RESTRICCION):
        op.execute(f"ALTER TABLE appointments DROP CONSTRAINT {RESTRICCION}")

    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        f"ALTER TABLE appointments ADD CONSTRAINT {RESTRICCION} "
        f"EXCLUDE USING gist ("
        f"  professional_id WITH =, "
        f"  {RANGO} WITH &&"
        f") WHERE ({VIVO})"
    )
    logger.info("✅ %s creada: la agenda ya tiene barrera en la base.", RESTRICCION)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if _existe(bind, RESTRICCION):
        op.execute(f"ALTER TABLE appointments DROP CONSTRAINT {RESTRICCION}")
    # Las marcas de sobreturno no se revierten: describen lo que realmente
    # habia en la agenda, no un efecto de esta migracion.
