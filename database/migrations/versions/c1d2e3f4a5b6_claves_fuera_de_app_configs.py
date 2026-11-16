"""claves fuera de app_configs y sin cascada de proveedores de IA

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-11-15 20:30:00.000000

Las claves (*_API_KEY, *_TOKEN, *_SECRET) pasan a leerse SOLO del entorno
(backend/services/config.py). Las que quedaban en app_configs ya no se usan y
eran justamente las que se veian desde el panel: se borran.

Tambien se va lo que dejo de existir: la cascada de proveedores (AI_PROVIDER*,
OPENROUTER_*, GROQ_*) y la configuracion de Telegram.

El downgrade no restaura nada: las claves viejas estan revocadas y las vigentes
viven en Dokploy. Antes de aplicar en produccion se respaldo la tabla.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b0c1d2e3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OBSOLETAS = (
    'AI_PROVIDER', 'AI_PROVIDER_2', 'AI_PROVIDER_3',
    'OPENROUTER_MODEL', 'GROQ_MODEL', 'TELEGRAM_WEBHOOK_URL',
)


def upgrade() -> None:
    op.execute(
        "DELETE FROM app_configs WHERE key LIKE '%\\_API\\_KEY' "
        "OR key LIKE '%\\_TOKEN' OR key LIKE '%\\_SECRET' "
        "OR key IN (" + ", ".join(f"'{k}'" for k in OBSOLETAS) + ")"
    )


def downgrade() -> None:
    pass
