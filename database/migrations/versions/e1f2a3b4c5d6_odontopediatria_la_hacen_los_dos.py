"""odontopediatria la atienden los dos profesionales

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-08-24 14:00:00.000000

La migracion anterior ato Odontopediatría a la especialidad del mismo nombre,
que en la base solo tiene Elena. Pero el consultorio aclaro que los turnos de
chicos los atienden los dos, igual que Control.

Se deja sin especialidad, que es como se expresa "lo puede atender cualquiera":
la anterior mandaba todos los turnos de chicos a Elena y le desbalanceaba la
agenda.

Solo se toca si sigue como la sembro la migracion anterior. Si alguien ya lo
edito desde el panel —que es la fuente de verdad— se respeta.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "tipos_consulta" not in sa.inspect(bind).get_table_names():
        return
    bind.execute(sa.text(
        "UPDATE tipos_consulta SET especialidad = NULL "
        "WHERE nombre = 'Odontopediatría' AND especialidad = 'Odontopediatría'"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if "tipos_consulta" not in sa.inspect(bind).get_table_names():
        return
    bind.execute(sa.text(
        "UPDATE tipos_consulta SET especialidad = 'Odontopediatría' "
        "WHERE nombre = 'Odontopediatría' AND especialidad IS NULL"
    ))
