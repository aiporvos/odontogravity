"""bandeja de derivaciones: pausar el bot no es avisarle a nadie

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-09-08 23:30:00.000000

El bot decia "dejé la consulta para que recepción lo revise" y lo unico que
pasaba era que se callaba treinta minutos. No habia ningun lado donde alguien
pudiera ver que un paciente estaba esperando.

Una paciente pidio cancelar su turno del dia siguiente. Su ficha venia de la
agenda de papel, sin DNI ni telefono —como el 85% de las fichas activas— asi
que el bot no pudo identificarla y la conversacion termino en "¿podrias darme
el nombre y apellido de otra persona?". Nadie se entero. El turno siguio en la
agenda.

Con esta tabla el bot solo puede decir que dejo la consulta si la fila existe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, None] = 'd6e7f8a9b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "derivaciones" in sa.inspect(bind).get_table_names():
        return

    motivo = sa.Enum("identidad", "pedido_de_persona", "clinico", "dato_faltante",
                     "otro", name="motivoderivacion")
    estado = sa.Enum("pendiente", "resuelta", name="estadoderivacion")
    motivo.create(bind, checkfirst=True)
    estado.create(bind, checkfirst=True)

    op.create_table(
        "derivaciones",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("remote_jid", sa.String(120), nullable=False),
        sa.Column("telefono", sa.String(30), nullable=True),
        sa.Column("motivo", motivo, nullable=False, server_default="otro"),
        sa.Column("resumen", sa.Text(), nullable=False),
        sa.Column("datos_aportados", sa.Text(), nullable=True),
        sa.Column("estado", estado, nullable=False, server_default="pendiente"),
        sa.Column("resuelta_por", sa.String(120), nullable=True),
        sa.Column("nota_de_cierre", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("resuelta_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_derivaciones_remote_jid", "derivaciones", ["remote_jid"])
    op.create_index("ix_derivaciones_estado", "derivaciones", ["estado"])
    op.create_index("ix_derivaciones_created_at", "derivaciones", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if "derivaciones" in sa.inspect(bind).get_table_names():
        op.drop_table("derivaciones")
    sa.Enum(name="motivoderivacion").drop(bind, checkfirst=True)
    sa.Enum(name="estadoderivacion").drop(bind, checkfirst=True)
