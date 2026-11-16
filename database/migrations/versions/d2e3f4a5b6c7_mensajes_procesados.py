"""mensajes_procesados: deduplicacion de webhooks en la base

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-11-15 20:45:00.000000

YCloud reintenta el webhook si no recibe 2xx a tiempo. El registro de mensajes
ya procesados vivia en memoria: se perdia en cada reinicio y no servia con mas
de un proceso. Ahora es una tabla; el INSERT ... ON CONFLICT lo hace atomico.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS: en los tests create_all ya la crea antes de migrar.
    op.execute(
        "CREATE TABLE IF NOT EXISTS mensajes_procesados ("
        " wamid VARCHAR(255) PRIMARY KEY,"
        " recibido TIMESTAMPTZ NOT NULL DEFAULT now())"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mensajes_procesados")
