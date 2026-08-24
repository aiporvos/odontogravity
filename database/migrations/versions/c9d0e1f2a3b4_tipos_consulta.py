"""tipos de consulta: duracion y especialidad configurables desde el panel

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
Create Date: 2026-08-24 12:00:00.000000

La configuracion del agendado vivia partida: las especialidades de cada
profesional en la base (editables desde el panel), pero la duracion de cada tipo
de turno y los sinonimos con que los pacientes lo nombran, escritos a mano en
appointment_service.py. La clinica podia dar de alta un profesional nuevo, pero
no podia decir cuanto dura una endodoncia sin tocar el codigo.

Esta tabla junta las tres cosas y se siembra con los valores que estaban
hardcodeados, asi el comportamiento no cambia al desplegar.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Exactamente lo que estaba en el codigo: (nombre, duracion, especialidad, sinonimos)
SEMILLA = [
    ("Control", 15, "Consulta",
     ["control", "revision", "chequeo", "consulta", "ver", "duele", "dolor", "puntos"]),
    ("Limpieza", 15, "Limpieza",
     ["limpiar", "limpieza", "sarro", "profilaxis", "higiene", "blanquear"]),
    ("Arreglos", 30, "Arreglos",
     ["arreglo", "arreglar", "caries", "tapar", "empaste", "roto", "rotura"]),
    ("Extracción", 30, "Extracción",
     ["sacar", "sacarme", "muela", "cordal", "extraer", "extraigan", "quitar", "extraccion"]),
    ("Ortodoncia", 30, "Ortodoncia",
     ["ortodoncia", "brackets", "aparato", "alinear", "invisalign"]),
    ("Prótesis", 30, "Prótesis",
     ["protesis", "placa", "dentadura", "puente", "implante"]),
    ("Conducto", 60, "Endodoncia",
     ["conducto", "endodoncia", "nervio", "matar el nervio"]),
]


def _tiene_tabla(tabla: str) -> bool:
    return tabla in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    # Crear la tabla y sembrarla son dos condiciones distintas. Si se guardan
    # juntas, una base donde create_all() ya creo la tabla se saltea tambien la
    # siembra y queda sin ningun tipo cargado: el bot pierde las duraciones sin
    # que nada falle.
    if not _tiene_tabla("tipos_consulta"):
        _crear_tabla()
    _sembrar_si_esta_vacia()


def _crear_tabla() -> None:
    op.create_table(
        "tipos_consulta",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nombre", sa.String(length=100), nullable=False, unique=True),
        sa.Column("duracion_minutos", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("especialidad", sa.String(length=100), nullable=True),
        sa.Column("sinonimos", postgresql.ARRAY(sa.String()), nullable=False,
                  server_default="{}"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
    )


def _sembrar_si_esta_vacia() -> None:
    ya_hay = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM tipos_consulta")
    ).scalar()
    if ya_hay:
        return   # la clinica ya los edito desde el panel; no se pisan

    # Las banderas y fechas van explicitas: si la tabla la creo create_all()
    # desde el modelo, sus defaults son de Python y un INSERT crudo como este
    # no los aplica, asi que is_active llegaria en NULL y violaria el NOT NULL.
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
    import uuid as _uuid
    from datetime import datetime as _dt
    ahora = _dt.utcnow()
    op.bulk_insert(tabla, [
        {"id": _uuid.uuid4(), "nombre": n, "duracion_minutos": d,
         "especialidad": e, "sinonimos": s,
         "is_active": True, "is_deleted": False,
         "created_at": ahora, "updated_at": ahora}
        for n, d, e, s in SEMILLA
    ])


def downgrade() -> None:
    if _tiene_tabla("tipos_consulta"):
        op.drop_table("tipos_consulta")
