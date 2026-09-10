"""un sobreturno solo puede salir del panel, nunca del bot

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-09-09 23:40:00.000000

Un sobreturno es una decision que toma recepcion mirando la agenda. El bot no
tiene con que tomarla: no ve la sala, no sabe si el paciente puede esperar, y
no puede pedirle permiso a nadie.

En el codigo ya era asi —create_appointment_logic no expone `force` y
motivo_no_agendable corta el alta— pero nada lo impedia a nivel base.

La regla NO puede ser "el canal no es de bot": `channel` dice quien CREO el
turno, no quien autorizo el sobreturno, y recepcion puede legitimamente
reprogramar desde el panel un turno que el bot habia creado. Se ve enseguida en
los tests: uno de reprogramacion se rompio al intentarlo.

Asi que se guarda quien lo autorizo. El panel escribe ese dato; el bot no tiene
como. Un sobreturno sin autorizacion registrada no puede existir.

Va como NOT VALID a proposito. Hay UNA fila historica que lo incumple: el turno
del 01/09 a las 11:00 que el bot agendo encima de otro porque la agenda estaba
partida en dos nombres de sede, y que la migracion f8a9b0c1d2e3 marco junto con
el resto de los solapamientos previos. Ese turno ya paso. Falsear su canal para
que entre en la regla seria borrar el registro de lo que realmente ocurrio; y
desmarcarlo romperia la restriccion de solapamientos. NOT VALID exige la regla
para todo lo nuevo y deja la historia como fue.
"""
from typing import Sequence, Union
import logging

from alembic import op
import sqlalchemy as sa

revision: str = 'a9b0c1d2e3f4'
down_revision: Union[str, None] = 'f8a9b0c1d2e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

RESTRICCION = "solo_el_panel_marca_sobreturnos"
REGLA = "is_overbooking = false OR overbooking_autorizado_por IS NOT NULL"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    if "appointments" not in inspector.get_table_names():
        return

    if not any(c["name"] == "overbooking_autorizado_por"
               for c in inspector.get_columns("appointments")):
        op.add_column("appointments", sa.Column(
            "overbooking_autorizado_por", sa.String(120), nullable=True))

    if bind.execute(sa.text(
        "SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": RESTRICCION}
    ).scalar():
        return

    incumplen = bind.execute(sa.text(
        f"SELECT count(*) FROM appointments WHERE NOT ({REGLA})"
    )).scalar()
    if incumplen:
        logger.info(
            "%s se crea como NOT VALID: %s fila(s) historica(s) la incumplen y "
            "se dejan como estan. La regla vale para todo lo nuevo.",
            RESTRICCION, incumplen,
        )

    op.execute(
        f"ALTER TABLE appointments ADD CONSTRAINT {RESTRICCION} "
        f"CHECK ({REGLA}) NOT VALID"
    )
    logger.info("✅ %s creada.", RESTRICCION)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if bind.execute(sa.text(
        "SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": RESTRICCION}
    ).scalar():
        op.execute(f"ALTER TABLE appointments DROP CONSTRAINT {RESTRICCION}")
    # La columna se deja: tiene el registro de quien autorizo cada sobreturno.
