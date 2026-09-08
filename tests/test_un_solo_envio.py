"""Que una respuesta lógica salga como UN mensaje, no dos.

C09 del plan de QA, verificado en el código.

_enviar_interactivo ya mandaba el texto de fallback por su cuenta cuando YCloud
rechazaba la lista o los botones, y después devolvía False. _responder leía ese
False como "no se envió nada" y mandaba el texto OTRA VEZ: al paciente le
llegaban dos mensajes idénticos.

Ahora el fallback lo decide un solo lugar, y el booleano significa "el paciente
recibió algo", no "salió como interactivo".
"""
import pytest

from backend.services import whatsapp


@pytest.fixture
def envios(monkeypatch):
    """Cuenta los textos planos que salen, sin tocar la red."""
    salidos = []

    async def _texto(number, text):
        salidos.append(text)
        return True

    monkeypatch.setattr(whatsapp, "send_whatsapp_message", _texto)
    return salidos


@pytest.fixture
def ycloud_rechaza(monkeypatch):
    """YCloud contesta 400 a cualquier interactivo."""
    class _Respuesta:
        status_code = 400
        text = "invalid interactive payload"

    class _Cliente:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return _Respuesta()

    monkeypatch.setattr(whatsapp.httpx, "AsyncClient", lambda *a, **k: _Cliente())
    monkeypatch.setattr(whatsapp, "get_config",
                        lambda k, d="": "x" if "KEY" in k else "+5492604590071")


@pytest.mark.asyncio
async def test_una_lista_rechazada_manda_un_solo_texto(envios, ycloud_rechaza):
    ok = await whatsapp.send_whatsapp_list(
        "+5492604590071", "Horarios:", ["09:00", "10:00"])
    assert len(envios) == 1, f"Salieron {len(envios)} mensajes: {envios}"
    assert ok is True, "El paciente recibió el texto: eso cuenta como enviado"


@pytest.mark.asyncio
async def test_botones_rechazados_mandan_un_solo_texto(envios, ycloud_rechaza):
    ok = await whatsapp.send_whatsapp_buttons(
        "+5492604590071", "¿Tenés obra social?", ["Sí", "No"])
    assert len(envios) == 1
    assert ok is True


@pytest.mark.asyncio
async def test_sin_configuracion_tambien_manda_uno_solo(envios, monkeypatch):
    monkeypatch.setattr(whatsapp, "get_config", lambda k, d="": "")
    ok = await whatsapp.send_whatsapp_list("+5492604590071", "Horarios:", ["09:00"])
    assert len(envios) == 1
    assert ok is True


@pytest.mark.asyncio
async def test_si_tampoco_sale_el_texto_se_informa(monkeypatch, ycloud_rechaza):
    """False tiene que significar que no llegó NADA."""
    async def _falla(number, text):
        return False

    monkeypatch.setattr(whatsapp, "send_whatsapp_message", _falla)
    ok = await whatsapp.send_whatsapp_list(
        "+5492604590071", "Horarios:", ["09:00", "10:00"])
    assert ok is False


@pytest.mark.asyncio
async def test_sin_opciones_va_directo_el_texto(envios, ycloud_rechaza):
    ok = await whatsapp.send_whatsapp_list("+5492604590071", "Sin horarios", [])
    assert envios == ["Sin horarios"]
    assert ok is True
