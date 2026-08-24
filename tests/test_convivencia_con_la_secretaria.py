"""Que el bot se corra cuando la secretaria toma la conversación.

Del primer día con pacientes reales (24/08/2026). La secretaria contestando en
paralelo con el bot, hasta tener que aclararle a la paciente:

    Silprodent: ESTA CONTESTANDO EL ASISTENTE VIRTUAL TAMBIEN JAJA
    Silprodent: EMPEZO A CONTESTAR EL ASISTENTE VIRTUAL PERO TU TURNO YA QUEDO AGENDADO

El mecanismo de pausa existía, pero nunca se disparaba: dependía de enterarse de
los mensajes que salen del número de la clínica, y el webhook solo tenía
habilitado `whatsapp.inbound_message.received`. Lo que la secretaria escribe
desde la app llega como `whatsapp.smb.message.echoes`, que no estaba suscripto.
"""
from datetime import datetime, timedelta

from backend.models.chat_session import ChatMessage, MessageRole
from backend.routers.evolution_router import (
    _minutos_de_pausa, _pausar_por_intervencion_humana, get_or_create_session,
)

JID = "5492604305278@s.whatsapp.net"


def _correr(coro):
    import asyncio
    return asyncio.run(coro)


def test_la_secretaria_silencia_al_bot(db):
    _correr(_pausar_por_intervencion_humana(JID, "TENES QUE VENIR DIRECTAMENTE"))

    session = get_or_create_session(db, JID)
    db.refresh(session)
    assert session.paused_until is not None, "El bot siguió contestando en paralelo"
    assert session.paused_until > datetime.utcnow()


def test_lo_que_dijo_la_secretaria_queda_en_el_historial(db):
    """Para que el bot no la contradiga cuando venza la pausa."""
    _correr(_pausar_por_intervencion_humana(JID, "TENES QUE VENIR DIRECTAMENTE"))

    session = get_or_create_session(db, JID)
    guardados = db.query(ChatMessage).filter(
        ChatMessage.session_id == session.id,
        ChatMessage.role == MessageRole.assistant,
    ).all()
    assert any("VENIR DIRECTAMENTE" in m.content for m in guardados)


def test_la_pausa_dura_lo_configurado(db):
    from backend.models.config import AppConfig

    db.add(AppConfig(key="MINUTOS_PAUSA_HUMANA", value="120"))
    db.commit()
    assert _minutos_de_pausa() == 120

    _correr(_pausar_por_intervencion_humana(JID, "yo me encargo"))
    session = get_or_create_session(db, JID)
    db.refresh(session)
    faltan = (session.paused_until - datetime.utcnow()).total_seconds() / 60
    assert 115 < faltan <= 120


def test_media_hora_por_defecto(db):
    assert _minutos_de_pausa() == 30


def test_un_valor_invalido_no_rompe_el_arranque(db):
    from backend.models.config import AppConfig

    db.add(AppConfig(key="MINUTOS_PAUSA_HUMANA", value="un rato"))
    db.commit()
    assert _minutos_de_pausa() == 30


def test_un_eco_sin_texto_igual_pausa(db):
    """Una foto o un audio de la secretaria también es tomar la conversación."""
    _correr(_pausar_por_intervencion_humana(JID, ""))

    session = get_or_create_session(db, JID)
    db.refresh(session)
    assert session.paused_until is not None
