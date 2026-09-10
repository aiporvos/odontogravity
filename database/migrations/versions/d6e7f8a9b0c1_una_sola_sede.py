"""una sola sede: todo pasa a llamarse Silprodent

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-09-08 20:00:00.000000

El consultorio tiene una sola sede, pero en la base estaba cargada con tres
nombres, y eso partia la agenda en tres:

    Silprodent   193 turnos (153 futuros)   <- la agenda real
    San Rafael   372 turnos ( 22 futuros)   <- donde agendaba el bot
    Silproden     15 turnos (  4 futuros)   <- con la 't' faltante

get_day_appointments filtraba por el nombre, asi que el bot no veia el 87% de
los turnos futuros y ofrecia como libres horarios ya tomados. El 01/09 a las
11:00 agendo un conducto de 60 minutos encima de un turno de 10:30 a 11:30
cargado como "Silprodent": misma profesional, un solo sillon.

Autorizado explicitamente por el responsable: "La sede es unica asi que no
importa, unificalas en una llamada Silprodent".

No se pierde informacion: la sede era el mismo lugar en los tres casos. Los
turnos con sede en NULL tambien pasan a Silprodent, porque ya no hay ninguna
otra a la que pudieran pertenecer.
"""
from typing import Sequence, Union
import logging

from alembic import op
import sqlalchemy as sa

revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

SEDE = "Silprodent"


def upgrade() -> None:
    bind = op.get_bind()
    tablas = sa.inspect(bind).get_table_names()
    if "appointments" not in tablas:
        return

    antes = bind.execute(sa.text(
        "SELECT coalesce(location, '(sin sede)') AS sede, count(*) "
        "FROM appointments WHERE is_deleted = false GROUP BY 1 ORDER BY 2 DESC"
    )).fetchall()
    logger.info("Sedes antes de unificar: %s",
                ", ".join(f"{s}={c}" for s, c in antes))

    movidos = bind.execute(sa.text(
        "UPDATE appointments SET location = :sede "
        "WHERE location IS DISTINCT FROM :sede"
    ), {"sede": SEDE}).rowcount
    logger.info("Turnos pasados a '%s': %s", SEDE, movidos)

    if "clinic_locations" not in tablas:
        return

    # El catalogo queda con una sola sede activa. Las demas no se borran —hay
    # historial que las nombra— sino que se desactivan.
    existe = bind.execute(sa.text(
        "SELECT 1 FROM clinic_locations WHERE name = :n"), {"n": SEDE}).scalar()
    if existe:
        bind.execute(sa.text(
            "UPDATE clinic_locations SET is_active = true, is_deleted = false "
            "WHERE name = :n"), {"n": SEDE})
    else:
        bind.execute(sa.text(
            "INSERT INTO clinic_locations (id, name, is_active, is_deleted, created_at) "
            "VALUES (gen_random_uuid(), :n, true, false, now())"), {"n": SEDE})

    desactivadas = bind.execute(sa.text(
        "UPDATE clinic_locations SET is_active = false "
        "WHERE name <> :n AND is_active = true"), {"n": SEDE}).rowcount
    logger.info("Sedes desactivadas del catalogo: %s", desactivadas)

    # Los profesionales tambien tenian la sede escrita a mano en su lista.
    if "professionals" in tablas:
        cols = [c["name"] for c in sa.inspect(bind).get_columns("professionals")]
        if "locations" in cols:
            # locations es un ARRAY de texto, no JSON.
            bind.execute(sa.text(
                "UPDATE professionals SET locations = ARRAY[:sede]::varchar[] "
                "WHERE locations IS DISTINCT FROM ARRAY[:sede]::varchar[]"
            ), {"sede": SEDE})


def downgrade() -> None:
    # Volver atras exigiria saber que nombre tenia cada turno, y esa distincion
    # no significaba nada: era el mismo lugar escrito de tres formas.
    pass
