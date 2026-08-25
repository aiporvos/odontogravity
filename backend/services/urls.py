"""La URL publica del sistema, en un solo lugar.

Estaba en tres: reminders_loop y admin_routes leian PUBLIC_APP_URL con default
"http://localhost:8000", y appointment_tools tenia el dominio escrito a mano.

Como PUBLIC_APP_URL no estaba configurada en produccion, los recordatorios
salieron a pacientes reales con un link a localhost:

    Hola Axel, te recordamos tu turno... cancelálo en el siguiente link:
    http://localhost:8000/api/public/cancel/2c8433df-...

Nadie puede cancelar desde ahi. Y el paciente que no puede cancelar, falta sin
avisar.
"""
import logging
import os

from sqlalchemy.orm import Session

from backend.models.config import AppConfig

logger = logging.getLogger(__name__)

_FALLBACK = "http://localhost:8000"


def url_publica(db: Session) -> str:
    """La URL por la que los pacientes llegan al sistema, sin barra final.

    Orden: la clave PUBLIC_APP_URL del panel, la variable de entorno, y por
    ultimo el primer origen no-local de ALLOWED_ORIGINS, que en produccion ya
    apunta al dominio real. Si aun asi queda en localhost se avisa fuerte: cada
    link que salga desde ahi es un paciente que no va a poder cancelar.
    """
    valor = ""
    try:
        conf = db.query(AppConfig).filter(AppConfig.key == "PUBLIC_APP_URL").first()
        if conf and conf.value:
            valor = conf.value.strip()
    except Exception:
        pass

    if not valor:
        valor = (os.getenv("PUBLIC_APP_URL") or "").strip()

    if not valor:
        # ALLOWED_ORIGINS en produccion ya tiene el dominio bueno.
        for origen in (os.getenv("ALLOWED_ORIGINS") or "").split(","):
            origen = origen.strip().rstrip("/")
            if origen and origen != "*" and "localhost" not in origen and "127.0.0.1" not in origen:
                valor = origen
                break

    if not valor:
        valor = _FALLBACK

    valor = valor.rstrip("/")

    if "localhost" in valor or "127.0.0.1" in valor:
        logger.error(
            "🔗 PUBLIC_APP_URL apunta a %s: los links de cancelación que se le "
            "mandan a los pacientes NO van a funcionar. Cargala en "
            "Configuración → Integraciones con el dominio real.",
            valor,
        )

    return valor


def link_de_cancelacion(db: Session, appointment_id) -> str:
    return f"{url_publica(db)}/api/public/cancel/{appointment_id}"
