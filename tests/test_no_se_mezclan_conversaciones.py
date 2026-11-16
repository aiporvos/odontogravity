"""Una conversación no arrastra datos de la anterior ni pierde confirmaciones.

Revisión del 15-16/11/2026, a pedido de Claudio ("se mezclan las respuestas"):

- El historial vencía a las 6 h y el estado (motivo, día, turno a medio sacar)
  no vencía nunca: el paciente volvía a la semana y el bot seguía el pedido viejo.
- "ok"/"dale" como respuesta a una pregunta del bot se tomaba por cierre: el
  modelo corría (y podía agendar) y la respuesta se tapaba con "¡De nada!".
- Un "gracias" llamaba igual a la IA.
- Si el paciente escribía mientras se generaba la respuesta, se descartaba
  aunque el turno ya estuviera agendado.
"""
import asyncio
import json
from datetime import datetime, timedelta

from backend.models.chat_session import ChatMessage, MessageRole
from backend.routers import whatsapp_router as er
from bot import flujo_turno

JID = "5492605550998@s.whatsapp.net"


def _armar(monkeypatch, chat_falso):
    enviados = []

    async def enviar(jid, texto, *a, **k):
        enviados.append(texto)
        return True

    async def sin_loop(*a, **k):
        return None, None, None

    monkeypatch.setattr(er, "chat", chat_falso)
    monkeypatch.setattr(er, "_responder", enviar)
    monkeypatch.setattr(er, "send_whatsapp_message", enviar)
    monkeypatch.setattr(er, "resolver_loop", lambda *a: (None, None, None))
    return enviados


def _mensaje_viejo(db, session, rol, texto, hace: timedelta):
    db.add(ChatMessage(session_id=session.id, role=rol, content=texto,
                       created_at=datetime.utcnow() - hace))
    db.commit()


def test_el_estado_vence_junto_con_el_historial(db, monkeypatch):
    visto = {}

    def chat_falso(text, history, phone, estado):
        visto["estado"] = estado
        return "¿En qué te ayudo?", None, estado

    _armar(monkeypatch, chat_falso)
    session = er.get_or_create_session(db, JID)
    session.context_data = json.dumps({"motivo": "Extracción", flujo_turno.CLAVE: {"activo": True}})
    db.commit()
    _mensaje_viejo(db, session, MessageRole.user, "quiero turno", timedelta(days=7))

    asyncio.run(er.handle_text_message(JID, "hola"))

    assert visto["estado"] == {}, "Arrastró datos de una charla de hace una semana"


def test_el_estado_sigue_dentro_de_la_misma_charla(db, monkeypatch):
    visto = {}

    def chat_falso(text, history, phone, estado):
        visto["estado"] = estado
        return "Listo.", None, estado

    _armar(monkeypatch, chat_falso)
    session = er.get_or_create_session(db, JID)
    session.context_data = json.dumps({"motivo": "Extracción"})
    db.commit()
    _mensaje_viejo(db, session, MessageRole.user, "quiero turno", timedelta(minutes=5))

    asyncio.run(er.handle_text_message(JID, "mañana a la tarde"))

    assert visto["estado"].get("motivo") == "Extracción"


def test_gracias_no_llama_a_la_ia(db, monkeypatch):
    def chat_falso(*a):
        raise AssertionError("Un 'gracias' no tiene que llegar al modelo")

    enviados = _armar(monkeypatch, chat_falso)
    session = er.get_or_create_session(db, JID)
    _mensaje_viejo(db, session, MessageRole.assistant, "Tu turno quedó agendado.", timedelta(minutes=1))

    asyncio.run(er.handle_text_message(JID, "Muchas gracias!"))

    assert enviados == ["¡De nada! Cualquier cosa, escribime. 😊"]


def test_ok_a_una_pregunta_del_bot_no_es_un_cierre(db, monkeypatch):
    def chat_falso(text, history, phone, estado):
        return "Tu turno quedó agendado para el lunes a las 10:00.", None, {}

    enviados = _armar(monkeypatch, chat_falso)
    session = er.get_or_create_session(db, JID)
    _mensaje_viejo(db, session, MessageRole.assistant,
                   "Tengo el lunes a las 10:00. ¿Te sirve?", timedelta(minutes=1))

    asyncio.run(er.handle_text_message(JID, "ok"))

    assert enviados == ["Tu turno quedó agendado para el lunes a las 10:00."]


def test_lo_agendado_se_confirma_aunque_escriba_de_nuevo(db, monkeypatch):
    def chat_falso(text, history, phone, estado):
        er.nueva_version(JID)      # el paciente escribió mientras se generaba
        return "Tu turno quedó agendado.", None, {"accion_hecha": True}

    enviados = _armar(monkeypatch, chat_falso)
    asyncio.run(er.handle_text_message(JID, "a las 10"))

    assert enviados == ["Tu turno quedó agendado."]
    guardado = json.loads(er.get_or_create_session(db, JID).context_data)
    assert "accion_hecha" not in guardado, "La marca no se guarda para la próxima vuelta"


def test_sin_accion_la_respuesta_vieja_se_descarta(db, monkeypatch):
    def chat_falso(text, history, phone, estado):
        er.nueva_version(JID)
        return "Tengo a las 11.", None, {}

    enviados = _armar(monkeypatch, chat_falso)
    asyncio.run(er.handle_text_message(JID, "11"))

    assert enviados == []
