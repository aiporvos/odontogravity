"""La cobertura la registra el código, no el modelo.

Charla real 21/09/2026: el paciente escribió "Avalian", el bot dijo "ya tengo
que tenés Avalian"… y la cobertura nunca quedó en el estado porque el modelo no
llamó a recordar_dato. Con la barrera de cobertura, eso vuelve a preguntar la
obra social a alguien que la acaba de decir.

Cuando la coincidencia es exacta (escribió el nombre o tocó la lista), no hay
nada que el modelo tenga que decidir: se registra acá.
"""
import os

import pytest
from fastapi.testclient import TestClient

from backend.models.insurance import Insurance
from bot.tools import appointment_tools as tools

NOMBRES = ["OSDE", "OSEP", "OSPELSYM", "Swiss Medical", "Avalian", "PAMI"]


@pytest.fixture
def muchas(db):
    db.query(Insurance).delete()
    db.add_all([Insurance(name=n, is_active=True) for n in NOMBRES])
    db.commit()


@pytest.fixture
def cliente(db, muchas):
    from backend.main import app
    with TestClient(app) as c:
        yield c


def _listar(cliente, q=None):
    r = cliente.get("/api/bot/obras-sociales", params={"q": q} if q else None,
                    headers={"x-bot-key": os.environ["BOT_API_KEY"]})
    assert r.status_code == 200, r.text
    return r.json()


# ── El backend dice si la coincidencia es exacta ─────────────────────────────

def test_el_backend_marca_la_coincidencia_exacta(cliente):
    assert _listar(cliente, "avalian")["exacta"] == "Avalian"
    assert _listar(cliente, "OSDE")["exacta"] == "OSDE"
    assert _listar(cliente, "swiss medical")["exacta"] == "Swiss Medical"


def test_un_fragmento_no_es_exacto(cliente):
    assert _listar(cliente, "ospe")["exacta"] is None
    assert _listar(cliente, "ava")["exacta"] is None
    assert _listar(cliente)["exacta"] is None


# ── Las tools registran solas ────────────────────────────────────────────────

def _con_backend(monkeypatch, respuesta_get=None, respuesta_post=None):
    class _R:
        def __init__(self, d): self._d = d
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return self._d

    if respuesta_get is not None:
        monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: _R(respuesta_get))
    if respuesta_post is not None:
        monkeypatch.setattr(tools.httpx, "post", lambda *a, **k: _R(respuesta_post))


def test_escribir_el_nombre_exacto_registra_la_cobertura(monkeypatch):
    _con_backend(monkeypatch, respuesta_get={
        "activas": ["Avalian"], "total": 6, "hay_mas": False,
        "busqueda": "avalian", "modo": "busqueda", "exacta": "Avalian",
    })
    tools.set_estado_conversacion({"cobertura_preguntada": True})
    tools.set_ultimo_mensaje("Avalian")

    r = tools.listar_obras_sociales()

    assert tools.get_estado_conversacion()["obra_social"] == "Avalian"
    assert "registrada" in r.lower()
    assert "no llames a `recordar_dato`" in r.lower(), "No hay nada que el modelo tenga que registrar"


def test_tocar_la_lista_registra_sin_confirmar(monkeypatch):
    """El texto de una fila es exacto: no tiene sentido preguntar '¿es esa?'."""
    _con_backend(monkeypatch, respuesta_get={
        "activas": ["OSDE"], "total": 6, "hay_mas": False,
        "busqueda": "osde", "modo": "busqueda", "exacta": "OSDE",
    })
    tools.set_estado_conversacion({})
    tools.set_ultimo_mensaje("OSDE")

    tools.listar_obras_sociales("OSDE")

    assert tools.get_estado_conversacion()["obra_social"] == "OSDE"
    assert tools.tomar_opciones_ofrecidas() is None, "No hay botones de confirmación"


def test_una_parecida_no_exacta_sigue_pidiendo_confirmacion(monkeypatch):
    _con_backend(monkeypatch, respuesta_get={
        "activas": ["OSPELSYM"], "total": 6, "hay_mas": False,
        "busqueda": "ospeysin", "modo": "busqueda", "exacta": None,
    })
    tools.set_estado_conversacion({})
    tools.set_ultimo_mensaje("ospeysin")

    tools.listar_obras_sociales("ospeysin")

    assert not tools.get_estado_conversacion().get("obra_social")
    pub = tools.tomar_opciones_ofrecidas()
    assert pub["tipo"] == "botones" and "OSPELSYM" in pub["opciones"]


def test_verificar_cubierta_registra(monkeypatch):
    _con_backend(monkeypatch, respuesta_post={
        "consultada": "osde", "cubierta": True, "nombre": "OSDE",
        "parecidas": [], "activas": NOMBRES,
    })
    tools.set_estado_conversacion({})

    tools.verificar_obra_social("osde")

    assert tools.get_estado_conversacion()["obra_social"] == "OSDE"


def test_registrar_pisa_particular_de_la_ficha(monkeypatch):
    """La ficha decía Particular; el paciente eligió su obra social."""
    _con_backend(monkeypatch, respuesta_get={
        "activas": ["PAMI"], "total": 6, "hay_mas": False,
        "busqueda": "pami", "modo": "busqueda", "exacta": "PAMI",
    })
    tools.set_estado_conversacion({"obra_social": "Particular"})
    tools.set_ultimo_mensaje("PAMI")

    tools.listar_obras_sociales()

    assert tools.get_estado_conversacion()["obra_social"] == "PAMI"


# ── La barrera resuelve en vez de mandar a preguntar ─────────────────────────

def test_la_barrera_registra_si_el_paciente_ya_la_nombro(monkeypatch):
    """Escribió 'Avalian' y el modelo fue derecho a consultar horarios."""
    _con_backend(monkeypatch, respuesta_get={
        "activas": ["Avalian"], "total": 6, "hay_mas": False,
        "busqueda": "avalian", "modo": "busqueda", "exacta": "Avalian",
    })
    tools.set_estado_conversacion({"motivo": "Limpieza"})
    tools.set_ultimo_mensaje("Avalian")

    bloqueo = tools._exigir_cobertura("consultar disponibilidad")

    assert bloqueo is None, f"Bloqueó aunque el paciente acababa de decir su obra social: {bloqueo}"
    assert tools.get_estado_conversacion()["obra_social"] == "Avalian"


def test_la_barrera_manda_a_listar_si_es_un_fragmento(monkeypatch):
    _con_backend(monkeypatch, respuesta_get={
        "activas": ["OSPE", "OSPELSYM"], "total": 6, "hay_mas": False,
        "busqueda": "ospe", "modo": "busqueda", "exacta": None,
    })
    tools.set_estado_conversacion({"motivo": "Limpieza", "cobertura_preguntada": True})
    tools.set_ultimo_mensaje("ospe")

    bloqueo = tools._exigir_cobertura("consultar disponibilidad")

    assert bloqueo and "listar_obras_sociales" in bloqueo
    assert "preguntar_cobertura" not in bloqueo, "No se vuelve a preguntar si tiene o no"
