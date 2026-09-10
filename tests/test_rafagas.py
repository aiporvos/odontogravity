"""Que tres mensajes seguidos reciban una respuesta, no tres cruzadas.

C01-C08 y H02 del plan de QA. Casos reales del 08/09/2026:

    paciente: Hola Mimi
    paciente: Cómo estás?
    paciente: Para cuándo tenes turno?
    bot:      Estoy bien, gracias 😊. ¿En qué puedo ayudarte hoy?
    bot:      No tengo turnos asociados a este número. ¿Me pasás tu DNI?

Dos respuestas, y la de "cómo estás" llegó DESPUÉS de la del turno. Cada mensaje
disparaba una generación completa e independiente. Otro paciente mandó cuatro
archivos y recibió cuatro veces el mismo aviso de formato no admitido.
"""
import asyncio

import pytest

from backend.routers import evolution_router as er


@pytest.fixture(autouse=True)
def rafagas_rapidas(monkeypatch):
    """Los tiempos reales son 3 s y 10 s; acá alcanzan milisegundos."""
    monkeypatch.setattr(er, "SILENCIO_ANTES_DE_RESPONDER", 0.05)
    monkeypatch.setattr(er, "ESPERA_MAXIMA", 0.4)
    er._lotes.clear()
    er._version_conversacion.clear()
    er._ultimo_aviso.clear()
    yield
    er._lotes.clear()


@pytest.fixture
def procesados(monkeypatch):
    """Qué le llegó a handle_text_message, sin tocar el modelo ni la base."""
    llamadas = []

    async def _falso(remote_jid, text, partes=None):
        llamadas.append({"texto": text, "partes": partes})

    monkeypatch.setattr(er, "handle_text_message", _falso)
    return llamadas


JID = "5492604590071@s.whatsapp.net"


# ── C01: la ráfaga se contesta una sola vez ─────────────────────────────────

@pytest.mark.asyncio
async def test_tres_mensajes_seguidos_son_una_sola_respuesta(procesados):
    for parte in ("Hola Mimi", "Cómo estás?", "Para cuándo tenes turno?"):
        await er.encolar_texto(JID, parte)
    await asyncio.sleep(0.2)

    assert len(procesados) == 1, f"Se generaron {len(procesados)} respuestas"
    assert procesados[0]["texto"] == "Hola Mimi\nCómo estás?\nPara cuándo tenes turno?"


@pytest.mark.asyncio
async def test_cada_parte_queda_registrada_por_separado(procesados):
    """El historial tiene que decir lo que la persona escribió, no el pegote."""
    for parte in ("Hola", "Necesito un turno"):
        await er.encolar_texto(JID, parte)
    await asyncio.sleep(0.2)

    assert procesados[0]["partes"] == ["Hola", "Necesito un turno"]


@pytest.mark.asyncio
async def test_un_mensaje_solo_no_espera_de_mas(procesados):
    await er.encolar_texto(JID, "Quiero un turno")
    await asyncio.sleep(0.2)
    assert len(procesados) == 1
    assert procesados[0]["texto"] == "Quiero un turno"


# ── C02: la corrección llega en el mismo lote ───────────────────────────────

@pytest.mark.asyncio
async def test_la_correccion_viaja_con_el_original(procesados):
    """«11» / «perdón, 12»: el modelo tiene que ver las dos."""
    await er.encolar_texto(JID, "11")
    await asyncio.sleep(0.02)
    await er.encolar_texto(JID, "perdón, 12")
    await asyncio.sleep(0.2)

    assert len(procesados) == 1
    assert procesados[0]["texto"] == "11\nperdón, 12"


@pytest.mark.asyncio
async def test_el_tope_corta_una_rafaga_interminable(procesados):
    """Quien escribe sin parar igual recibe respuesta."""
    for i in range(20):
        await er.encolar_texto(JID, f"parte {i}")
        await asyncio.sleep(0.03)
    await asyncio.sleep(0.2)

    assert procesados, "Nunca contestó: la espera se reiniciaba para siempre"


# ── Dos conversaciones no se mezclan ────────────────────────────────────────

@pytest.mark.asyncio
async def test_cada_conversacion_tiene_su_lote(procesados):
    otro = "5492604111222@s.whatsapp.net"
    await er.encolar_texto(JID, "soy uno")
    await er.encolar_texto(otro, "soy otro")
    await asyncio.sleep(0.2)

    textos = sorted(p["texto"] for p in procesados)
    assert textos == ["soy otro", "soy uno"]


# ── C03: una respuesta que quedó vieja no sale ──────────────────────────────

@pytest.mark.asyncio
async def test_la_version_sube_con_cada_parte():
    v0 = er.version_actual(JID)
    await er.encolar_texto(JID, "uno")
    await er.encolar_texto(JID, "dos")
    assert er.version_actual(JID) == v0 + 2


# ── H02: recepción tiene prioridad ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_toma_humana_cancela_el_lote_en_espera(procesados, monkeypatch):
    """Si la secretaria contesta, lo que el bot iba a decir no sale."""
    class _Sesion:
        id = 1
        paused_until = None

    monkeypatch.setattr(er, "get_or_create_session", lambda db, jid: _Sesion())
    monkeypatch.setattr(er, "save_message", lambda *a, **k: None)
    monkeypatch.setattr(er, "SessionLocal", lambda: type(
        "S", (), {"commit": lambda s: None, "close": lambda s: None})())
    monkeypatch.setattr(er, "_minutos_de_pausa", lambda: 30)

    await er.encolar_texto(JID, "hola, quiero un turno")
    await er._pausar_por_intervencion_humana(JID, "hola, te atiendo yo")
    await asyncio.sleep(0.2)

    assert procesados == [], "El bot contestó encima de la secretaria"


@pytest.mark.asyncio
async def test_la_toma_humana_invalida_lo_que_se_este_generando(monkeypatch):
    class _Sesion:
        id = 1
        paused_until = None

    monkeypatch.setattr(er, "get_or_create_session", lambda db, jid: _Sesion())
    monkeypatch.setattr(er, "save_message", lambda *a, **k: None)
    monkeypatch.setattr(er, "SessionLocal", lambda: type(
        "S", (), {"commit": lambda s: None, "close": lambda s: None})())
    monkeypatch.setattr(er, "_minutos_de_pausa", lambda: 30)

    await er.encolar_texto(JID, "hola")
    version_de_la_respuesta = er.version_actual(JID)
    await er._pausar_por_intervencion_humana(JID, "te atiendo yo")

    assert er.version_actual(JID) != version_de_la_respuesta


# ── C08: un aviso por tanda de archivos ─────────────────────────────────────

def test_cuatro_archivos_seguidos_avisan_una_vez():
    assert er._corresponde_avisar(JID) is True
    assert [er._corresponde_avisar(JID) for _ in range(3)] == [False, False, False]


def test_cada_conversacion_recibe_su_aviso():
    otro = "5492604111222@s.whatsapp.net"
    assert er._corresponde_avisar(JID) is True
    assert er._corresponde_avisar(otro) is True


def test_pasada_la_ventana_se_vuelve_a_avisar(monkeypatch):
    assert er._corresponde_avisar(JID) is True
    monkeypatch.setattr(er, "VENTANA_DE_AVISO", 0.0)
    assert er._corresponde_avisar(JID) is True
