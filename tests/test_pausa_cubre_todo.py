"""Con el bot pausado no sale NINGUNA respuesta automática.

Reportado desde producción el 01/09/2026: la secretaria estaba atendiendo esa
conversación a mano, el bot figuraba pausado, y un paciente mandó un PDF de
OSPELSYM. El bot le contestó igual:

    "¡Hola! 🦷 Por el momento solo puedo procesar mensajes de texto y audio..."

La pausa se verificaba únicamente dentro de handle_text_message, así que todo lo
que se respondía directo desde el webhook —archivos, ubicaciones, contactos, y
el aviso de audio ilegible— se saltaba el control por completo.
"""
from datetime import datetime, timedelta

import pytest

from backend.models.config import AppConfig
from backend.routers.evolution_router import bot_silenciado, get_or_create_session

JID = "5492604305278@s.whatsapp.net"


def test_por_defecto_el_bot_responde(db):
    assert bot_silenciado(JID) is False


def test_el_interruptor_global_lo_calla(db):
    db.add(AppConfig(key="BOT_IS_ACTIVE", value="false"))
    db.commit()
    assert bot_silenciado(JID) is True


def test_una_conversacion_pausada_lo_calla(db):
    """El caso real: la secretaria la está atendiendo a mano."""
    session = get_or_create_session(db, JID)
    session.paused_until = datetime.utcnow() + timedelta(minutes=30)
    db.commit()

    assert bot_silenciado(JID) is True


def test_una_pausa_vencida_ya_no_lo_calla(db):
    """Vence sola: nadie queda sin bot para siempre por un descuido."""
    session = get_or_create_session(db, JID)
    session.paused_until = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    assert bot_silenciado(JID) is False


def test_la_pausa_es_por_conversacion(db):
    """Callar una charla no puede callar al resto de los pacientes."""
    session = get_or_create_session(db, JID)
    session.paused_until = datetime.utcnow() + timedelta(minutes=30)
    db.commit()

    assert bot_silenciado(JID) is True
    assert bot_silenciado("5492604000999@s.whatsapp.net") is False


def test_ante_un_error_responde_igual(db, monkeypatch):
    """Peor que responder de más es dejar al paciente sin ninguna respuesta."""
    from backend.routers import evolution_router as er

    def explota(*a, **k):
        raise RuntimeError("base caída")

    monkeypatch.setattr(er, "get_or_create_session", explota)
    assert bot_silenciado(JID) is False


# ── Los avisos automáticos también son respuestas del bot ───────────────────

def test_el_aviso_de_archivo_no_soportado_respeta_la_pausa(db):
    """Un PDF con el bot pausado no puede disparar el aviso de 'solo texto'."""
    session = get_or_create_session(db, JID)
    session.paused_until = datetime.utcnow() + timedelta(minutes=30)
    db.commit()

    # Es el chequeo que el webhook hace antes de contestar un image/video/document.
    assert bot_silenciado(JID) is True, (
        "El aviso de archivo no soportado se seguiría enviando"
    )
