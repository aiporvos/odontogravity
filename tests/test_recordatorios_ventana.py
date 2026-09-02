"""Que los recordatorios lleguen de verdad, y que el log no mienta.

WhatsApp solo deja mandar texto libre dentro de una ventana de 24 horas que
abre el paciente al escribir. Fuera de esa ventana lo rechaza y hay que usar una
plantilla aprobada.

Un recordatorio sale el día ANTES del turno, así que casi siempre cae fuera. Los
recordatorios solo llegaban a quien justo había escrito ese día — y nadie se
enteró porque send_whatsapp_message se tragaba el rechazo y el loop escribía
"Recordatorio enviado" igual.
"""
from datetime import datetime, timedelta

import pytest

from backend.models.chat_session import (
    ChatMessage, ChatPlatform, ChatSession, MessageRole,
)
from backend.services.reminders_loop import dentro_de_la_ventana

TELEFONO = "+5492604590071"
JID = "5492604590071@s.whatsapp.net"


def _escribio_hace(db, horas: float):
    session = ChatSession(platform=ChatPlatform.whatsapp, platform_user_id=JID)
    db.add(session)
    db.commit()
    db.refresh(session)
    db.add(ChatMessage(
        session_id=session.id, role=MessageRole.user, content="hola",
        created_at=datetime.utcnow() - timedelta(hours=horas),
    ))
    db.commit()


# ── Detectar la ventana ─────────────────────────────────────────────────────

def test_un_paciente_que_nunca_escribio_esta_fuera(db):
    assert dentro_de_la_ventana(db, TELEFONO) is False


def test_escribio_hace_dos_horas_esta_dentro(db):
    _escribio_hace(db, 2)
    assert dentro_de_la_ventana(db, TELEFONO) is True


def test_escribio_hace_treinta_horas_esta_fuera(db):
    """El caso típico del recordatorio: el paciente sacó turno la semana pasada."""
    _escribio_hace(db, 30)
    assert dentro_de_la_ventana(db, TELEFONO) is False


def test_justo_en_el_borde(db):
    _escribio_hace(db, 23.5)
    assert dentro_de_la_ventana(db, TELEFONO) is True


def test_lo_que_escribio_el_BOT_no_abre_la_ventana(db):
    """La ventana la abre el paciente, no las respuestas del bot."""
    session = ChatSession(platform=ChatPlatform.whatsapp, platform_user_id=JID)
    db.add(session)
    db.commit()
    db.refresh(session)
    db.add(ChatMessage(session_id=session.id, role=MessageRole.assistant,
                       content="Tu turno quedó agendado",
                       created_at=datetime.utcnow()))
    db.commit()

    assert dentro_de_la_ventana(db, TELEFONO) is False


def test_reconoce_el_telefono_en_otro_formato(db):
    """La ficha guarda +549..., la sesión guarda 549...@s.whatsapp.net."""
    _escribio_hace(db, 1)
    assert dentro_de_la_ventana(db, "2604590071") is True
    assert dentro_de_la_ventana(db, "+54 9 2604 59-0071") is True


def test_no_confunde_a_otro_paciente(db):
    _escribio_hace(db, 1)
    assert dentro_de_la_ventana(db, "+5492604000999") is False


def test_un_telefono_invalido_no_rompe(db):
    assert dentro_de_la_ventana(db, "") is False
    assert dentro_de_la_ventana(db, "123") is False
    assert dentro_de_la_ventana(db, None) is False


# ── El envío elige el canal correcto ────────────────────────────────────────

@pytest.mark.asyncio
async def test_dentro_de_la_ventana_va_texto_libre(db, monkeypatch, clinica, silvestro, paciente):
    """Es gratis: no tiene sentido gastar una plantilla."""
    from backend.services import reminders_loop as rl
    from conftest import proximo_dia_habil, turno

    usados = []

    async def _texto(*a, **k):
        usados.append("texto")
        return True

    async def _plantilla(*a, **k):
        usados.append("plantilla")
        return True

    monkeypatch.setattr(rl, "send_whatsapp_message", _texto)
    monkeypatch.setattr(rl, "send_whatsapp_template", _plantilla)
    _escribio_hace(db, 1)

    a = turno(db, paciente, silvestro, proximo_dia_habil())
    ok = await rl.enviar_recordatorio(db, a, paciente, "26/08 10:00", "http://x", "msg")

    assert ok is True
    assert usados == ["texto"]


@pytest.mark.asyncio
async def test_fuera_de_la_ventana_va_la_plantilla(db, monkeypatch, clinica, silvestro, paciente):
    """Es la única forma de reabrir la conversación."""
    from backend.services import reminders_loop as rl
    from conftest import proximo_dia_habil, turno

    usados = []

    async def _texto(*a, **k):
        usados.append("texto")
        return True

    async def _plantilla(*a, **k):
        usados.append("plantilla")
        return True

    monkeypatch.setattr(rl, "send_whatsapp_message", _texto)
    monkeypatch.setattr(rl, "send_whatsapp_template", _plantilla)
    _escribio_hace(db, 30)

    a = turno(db, paciente, silvestro, proximo_dia_habil())
    ok = await rl.enviar_recordatorio(db, a, paciente, "26/08 10:00", "http://x", "msg")

    assert ok is True
    assert usados == ["plantilla"], "Mandó texto libre fuera de la ventana: lo rechaza WhatsApp"


@pytest.mark.asyncio
async def test_si_la_plantilla_no_esta_aprobada_igual_se_intenta(
    db, monkeypatch, clinica, silvestro, paciente
):
    """Mientras Meta la revisa, mejor intentar el texto que no mandar nada."""
    from backend.services import reminders_loop as rl
    from conftest import proximo_dia_habil, turno

    usados = []

    async def _texto(*a, **k):
        usados.append("texto")
        return True

    async def _plantilla(*a, **k):
        usados.append("plantilla")
        return False   # todavía PENDING

    monkeypatch.setattr(rl, "send_whatsapp_message", _texto)
    monkeypatch.setattr(rl, "send_whatsapp_template", _plantilla)
    _escribio_hace(db, 30)

    a = turno(db, paciente, silvestro, proximo_dia_habil())
    ok = await rl.enviar_recordatorio(db, a, paciente, "26/08 10:00", "http://x", "msg")

    assert usados == ["plantilla", "texto"]
    assert ok is True


@pytest.mark.asyncio
async def test_si_no_llega_por_ningun_lado_se_informa(
    db, monkeypatch, clinica, silvestro, paciente
):
    """El fallo tiene que ser visible: antes decía 'enviado' igual."""
    from backend.services import reminders_loop as rl
    from conftest import proximo_dia_habil, turno

    async def _falla(*a, **k):
        return False

    monkeypatch.setattr(rl, "send_whatsapp_message", _falla)
    monkeypatch.setattr(rl, "send_whatsapp_template", _falla)
    _escribio_hace(db, 30)

    a = turno(db, paciente, silvestro, proximo_dia_habil())
    assert await rl.enviar_recordatorio(db, a, paciente, "26/08 10:00", "http://x", "msg") is False
